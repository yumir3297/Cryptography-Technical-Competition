# 时间与接受事实观察：精确候选合同0.2

日期：2026-10-10。标识`ZJJ-TIME-RESEARCH/0.2`。状态：研究候选，供独立审查与实现；原R2合同不变。本合同精化[0.1草案](05_time_acceptance_recovery_PROPOSED.md)，发生研究内部差异以本文件为准。

## 1. 保证和成立前提

处理接受前时间流逝、跨秒回执签署、原回执从未签好/到期/原钥撤销后的历史观察。保留R2逻辑接受语义：在同一受保护W事务中的授权守卫全T，COMMIT/Core冻结，持久提交后事实成立。授权在守卫时有效，不宣称磁盘提交或设备动作的物理时刻仍未到期。

可信前提A1–A6：A1可信区间覆盖对应检查事件并且宽度≤2秒；A2 W线性化隔离、原子持久提交、响应/nonce CAS正确；A3 C认证的主体/公钥/用途/角色/范围/操作查询权和撤销状态正确；A4 原完整接受档案真实、合法性可审核，原意图/消费/终态墓碑永久保存；A5 连续账不分叉、不回退，并通过**不随W备份一起回退的受信高水位与根代恢复治理锚**验证；A6 SHA-256碰撞抗性、严格Ed25519不可伪造及私钥保护。诚实W/C/观察者仍是信任模型。客户端自报根、roles、账名、摘要、hashchain或同一个ledger字符串均不证明这些前提。

原回执签名仍遵守R2真实签署时资格和时效，做不到即待恢复。新观察通道单独规定：**候选签名是预计算；协议认证资格以W的PublishObservation事件为准**。未发布的密码正确签名无协议效力，不声称这关闭了私钥设备物理签名时刻的撤销窗口。

## 2. 时间规则

每个当前检查采用其事件可信区间`I=[lo,hi]`：结构合法、宽度≤2、lo不小于持久下界；`iat<=lo && hi<exp`为T，`lo>=exp`为F，其他为U。更新下界与有效操作同事务提交，持久下界取`max(old_floor,lo)`，不能将不确定上界hi当成已知真实下界；先前区间hi可以大于随后更精确区间hi。无可信总年龄界的旧样本为U；有样本I0、覆盖从采样到当前事件的总年龄界D时，当前区间`[I0.lo+D.lo,I0.hi+D.hi]`，宽度和所有误差重新检查。网络传输年龄、漂移、重启/回退均不能漏算。

原接受时间`accepted_at=COMMIT.trusted_time.lo`冻结，原Acceptance iat等于它且exp≤iat+900。Permit已到期不抹除接受事实。新观察iat/exp只定义当前认证窗口，不改accepted_at、dispatch_before或任何业务授权。

## 3. 编码与域

沿用R2受限JCS、ASCII键、字符串整数、严格base64url、禁number/null/重复键/BOM/未知字段/非法Unicode/非规范字节。Query和Observation每个≤65536字节；Package≤1048576；JSON深度≤32，数组≤256，归档嵌套原对象仍遵守R2原对象限制。无隐式Profile或版本协商；支持PAY-1/IND-DEMO-1/MED-DEMO-1，对应scenario。

```text
Header(type)={proto:"ZJJ-TIME-RESEARCH",version:"0.2",profile,
              alg:"Ed25519",type,issuer:Id,kid:B32}
Sign(h,b)=Enc(["ZJJ-TIME-SIG-PROPOSED-v2",h,b])
QueryRef(q)=B64url(SHA256(Enc(["ZJJ-TIME-QUERY-PROPOSED-v2",q.protected,q.body])))
ObservationRef(p)=B64url(SHA256(Enc(["ZJJ-TIME-OBS-PROPOSED-v2",p.protected,p.body])))
CoreDigest(core)=B64url(SHA256(Enc(["ZJJ-TIME-CORE-PROPOSED-v2",core])))
FactID(f)=B64url(SHA256(Enc(["ZJJ-ACCEPT-FACT-PROPOSED-v2",f])))
PackageDigest(wire)=B64url(SHA256(wire))
```

R2 AH、KeyID、RecordRef及原Acceptance Ref算法逐字保留。ObservationRef不含sig，可信发布记录必须另绑定PackageDigest及**完整规范Package字节**，不能用同Ref的坏签名替换。新对象不能进入原R2 Bundle/Result引用库，不能叫正式2.6 Acceptance。

## 4. 两个签名对象与归档包

全部字段必需且无额外字段，整数为R2 N/Positive字符串，aud为规范排序非空Id集合。

```text
Query={protected:Header("AcceptanceObservationQuery"),
 body:{id:B16,scope:Scope,iat:N,exp:N,aud:Set(Id),
       operation_id:B16,session_id:B16,nonce:B32,attempt_id:B16},sig:B64}

Fact={profile,scope,operation_id:B16,action_hash:B32,
      ledger_origin:Id,accept_seq:Positive,accepted_at:N,
      commit_record_ref:B32,original_acceptance_ref:B32,original_core_digest:B32}

Snapshot={status:ACCEPTED|EFFECT_UNKNOWN|SUCCEEDED|FAILED_CONFIRMED|HALTED,
          status_seq:Positive,observed_time:{lo:N,hi:N}}

Observation={protected:Header("AcceptanceObservation"),
 body:{id:B16,scope:Scope,iat:N,exp:N,aud:Set(Id),
       query_ref:B32,query_nonce:B32,fact:Fact,fact_id:B32,snapshot:Snapshot,
       control_revision:Positive,ledger_epoch:Positive,history_anchor_ref:B32},sig:B64}

Archive={format:"ZJJ-CORE-ARCHIVE-PROPOSED-2",
         original_core:{protected:R2AcceptanceHeader,body:R2AcceptanceBody},
         commit:R2COMMITRecord}

Package={format:"ZJJ-TIME-PACKAGE-PROPOSED-2",observation:Observation,archive:Archive}
```

Query与Observation寿命均≤30秒。Query aud恰为本次C固定映射的受信观察者subject/kid所对应subject，Observation aud恰为当前Query.issuer；profile/scope均匹配可信服务配置、Query、Fact、原Core和COMMIT。观察者可以独立于原POLICY.executor，但必须由C明确固定当前subject/kid与scope/账授权，不能任选同subject其他钥。Query.session/nonce由W通过受控挑战入口受控创建，固定绑定查询主体kid/op/aud/attempt/窗口；nonce不可由客户端任意声明。Query.iat不早于挑战iat，Query.exp不晚于挑战exp，不为过期挑战续命。挑战入口不是原R2 /challenge，将来运输实现须固定新路径`/research/zjj/time-closure/0.2/challenge`和`/observe`，禁止fallback。研究检查器只检查可信挑战记录输入，不实现网络入口。

Observation.query_ref/nonce精确绑定已验证的Query。exp不晚于Query.exp、当前查询者及观察者Key/Role/用途授权exp和iat+30；iat≥Snapshot.observed_time.hi；Publish事件不早于iat，接收时全部当前守卫仍T。Snapshot.status_seq≥Fact.accept_seq；状态来自同次W快照，status_seq/状态可在随后变更，证明不承诺接收时全局最新。返回这个带时间和序号的历史状态快照不等于重新执行许可。

Archive.original_core没有sig，明确只是W冻结的原保护头/正文。单独查其R2 Acceptance结构、aud/deps/refs和归档绑定；COMMIT按该Profile原Schema。不得制造一个sig为空或占位的Envelope。CoreDigest/原Ref重新计算；原Core payload.ctx与COMMIT.ctx、动作/时间/许可/Proof/批准/审查/dispatch完全一致。AH重算COMMIT.action，frozen_tool_request必须相等，signing_public_key的KeyID等于原kid，trusted_time合法且accepted_at=lo。原Core.body.iat等于accepted_at，寿命≤900。所有原对象/资格/资源见证的完整合法性由A4历史审计入口核验，结构和摘要绑定不代替该入口。

Fact字段只从认证归档重建，不从请求者选择的Fact复制。原RecordRef按原COMMIT精确值重算，原Core.ref冻结；FactID包含完整Fact。查询操作必须与归档op一致。

## 5. 当前资格、账锚和发布

新用途`AcceptanceObservationQuery`与`AcceptanceObservation`及角色`HISTORY_OBSERVER`须由独立扩展治理登记显式批准；原R2 KEY_GRANT/Role固定枚举不接受这些值。本候选使用认证管理适配器提供完整可信当前元组：subject/pk/kid/profile/scope/purpose/role/iat/exp/active、控制revision、当前op访问权。这里iat为KEY、ROLE、新用途批准及访问权各自生效时间的最大值，exp为它们各自到期时间的最小值，active是所有未撤销/当前映射有效条件的合取；没有完整交集输入即U。控制revision覆盖其中每项及Task委托/服务观察者固定映射变化，严格增加，防ABA。KeyID(pk)=kid，严格点验证。Query者需当前HOLDER及当前Task委托的该op查询权，原holder可被更换。观察者需HISTORY_OBSERVER及此scope/账历史观察权限；不得复用EXECUTOR/READ推断。接收端独立读取当前受信元组，客户端附件不授予身份。

受信历史锚包括ledger_origin/ledger_epoch、独立恢复根/高水位、历史范围覆盖和原accept_seq/墓碑连续性。通过A5认证入口取得，hash只用于绑定已认证锚。恢复到旧前缀、无独立高水位、档案缺失或来源不可知均U；确认伪造/分叉为完整性失败，停止肯定认证，不谎报“没有接受”。

步骤：

1. 认证Query和当前授权、严格验签、当前时间、可信挑战记录，查询nonce未消费；在同受保护快照读取真实接受档案/当前状态/控制revision/账锚，持久或受保护保存FrozenReadWitness：query_ref、原档案字节及摘要、Fact、status/status_seq/observed_time、control_revision、ledger_epoch和history_anchor_ref。候选Observation及Archive须与这个受信读见证逐字段一致；客户端或签名器不能自行选择状态。
2. 对候选Observation预计算签名，签名输出不形成成功。iat来自新的可信时间样本；窗口全部T；若在W发布前过期，候选作废。
3. `PublishObservation(expected_control_revision,expected_ledger_epoch,query_ref)`在受保护W事务中重查完整当前Query者/观察者资格与授权范围、query时间和proof时间、受信历史和连续锚；控制/账epoch与快照精确相等，防ABA。核候选签名、完整Archive、Fact和Snapshot与FrozenReadWitness精确一致，核未消费session/nonce绑定；保存精确原Package字节、PackageDigest、ObservationRef、query_ref、nonce、publish_seq、publish_time、当时资格和锚见证，消费nonce。原操作状态/占用/消费/派发/结算一律不改。完整成功响应在此持久提交后才可输出。
4. 不明提交先恢复发布决定。同Query同Ref只返回已持久保存的**原Package字节**；同nonce异Query为REPLAY。没有保存完整响应时不返回成功。换新Query才可新认证；不自动给旧Query改iat/exp/状态。重传可返回过期历史字节，客户端不能将其当新鲜观察。
5. 客户端验Package和Query规范字节、双签名/当前资格/窗口/aud/scope/Fact/Archive全部绑定，并从权威W认证入口核对**该精确Package的原已提交发布记录**及连续历史，确认当时发布守卫见证正确。仅有新签名而没有受信发布记录为U。本候选采取保守规则：接收时control_revision和ledger_epoch须仍等于证明与发布见证，不相等为U/RETRY_CONFLICT，发新查询重新冻结；撤销后旧证明不能充当当前认证，可由新授权者认证同一事实。

可信发布记录为受控W证据，不是客户端可伪造JSON“published=true”。研究检查器的TrustedPublication由测试固定可信输入模拟，未实现该证据运输或W治理。若未来需离线独立验证发布，必须定义新的权威发布签名/透明账证明及完整信任模型，不能仅把本记录JSON放进Package。

## 6. 失败、副作用及迁移

新通道检查器报告T/F/U及固定研究错误：FORMAT/SIGNATURE/BINDING/CURRENT_AUTH/EXPIRED/REPLAY为F；CLOCK_UNKNOWN/AUTHORITY_UNAVAILABLE/HISTORY_UNAVAILABLE/PUBLICATION_UNAVAILABLE/RETRY_CONFLICT为U；原事实完整性冲突单独上报。失败返回不是原R2 Result，运输异常和U不能表示从未接受。没有可核验历史时不构造否认接受的成功包。

观察只能追加查询nonce/响应账和观察审计记录。业务接受/Permit消费/intent墓碑/资源/Behavior/Flight/attempt/FinalFactID/结算均零增量。当前Snapshot即使HALTED也可认证“过去接受过且该快照已HALTED”，不得自动解停。已started始终不重派，超时也不释放。

新通道提供独立观察接口，原R2四路径继续原矩阵；新的Observation永远不满足旧Result.acceptance_ref→Acceptance解析。拟合并时应完整声明新通道、资格管理适配器及C/W认证接口。若要在Result/Bundle内支持新附件，必须另冻结版本、精确Ref类型、机器Schema和迁移，不能局部扩大旧enum。

## 7. 派发和设备期限的条件

原领取前当前守卫与dispatch_before保留。新历史观察不延长它们。单凭授权服务器协议无法保证设备物理动作前仍有效：两个执行直到最后服务检查相同，其中一条随后立刻动作，另一条被延迟到过期后才动作；如果设备不检查时间/版本，它看到同一请求就无法区分。

要求更强模式时，必须把检查移动到工具端效果线性化点：工具认证冻结Action/op/原attempt，查当前围栏/撤销序、可信时间上界严格小于deadline，并将本attempt唯一效果决定与守卫原子提交；过期或U时不启动效果。重复仅查原决定，不二次执行。围栏只有工具端检查并与效果决定同序才成立。

工具独立服务与W之间的撤销边界应定义为“工具效果决定点前已入**工具权威序**的撤销”，W已知但尚未传播的撤销不能保证立即阻止。若要求W撤销实时约束物理设备，则须共用线性化协调/在线授权并锁住效果决定，分区时停用；不能凭异步消息承诺即时撤销。机械/医疗效果持续跨deadline时还需工具/硬件有界动作时间及停机保证：已启动不可中断动作不能凭签名取消。本候选不冒称已具备设备保证。

## 8. 关闭标准与局限

在A1–A6前提及本合同转换下，时间守卫、既有事实长期观察（一次有效当前窗口）、签名/发布竞态、请求绑定与恢复无执行副作用可给条件安全论证。服务最终可达不保证每次30秒窗口成功；有界读取/签名/发布/运输/接收耗时之和及区间误差均小于各资格剩余窗口，且授权/档案/连续账稳定时才有一次完成保证。

配套Schema/向量/检查器/有限探索是研究证据，不证明A1–A6已被真实软件实现，不替代原39/产品66验收，也不是恶意W历史证明。没有这些前提的无条件恢复及设备物理期限，已经给出不可实现情形或工具参与义务，不能报告“所有实际问题已解决”。
