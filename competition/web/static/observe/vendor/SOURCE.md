# dagre 0.8.5

- 上游：https://github.com/dagrejs/dagre
- 包：https://registry.npmjs.org/dagre/-/dagre-0.8.5.tgz
- 文件：`dagre.min.js`（`dist/dagre.min.js`，UMD，内含 `graphlib`）
- 许可证：MIT，全文见同目录 `dagre.LICENSE`

页面只用它算有向图的节点坐标与折线点：总图 12 块、块内节点的分层
（`rankdir: LR`）都由它给出，再按返回的坐标自己画方块和线。它不产出
任何图片，也不参与取数。

升级时替换 `dagre.min.js`、更新上面的版本号与 `dagre.LICENSE`。
