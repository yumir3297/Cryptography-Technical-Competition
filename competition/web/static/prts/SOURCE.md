# PRTS Design（CSS 快照）

观察面使用的设计底座来自 [MooncellWiki/prts-design](https://github.com/MooncellWiki/prts-design)，
即 prts.wiki 新版皮肤的设计系统。本目录只包含**展平后的 CSS 代码**，不含字体与游戏素材。

- 上游仓库：`https://github.com/MooncellWiki/prts-design`
- 固定提交：`38b02e40eee09d92e2314e234020f825eda75e2b`（2026-11-10）
- 抓取日期：2026-11-25
- 抓取入口：`packages/css/src/standalone.css`
- 展平范围：该入口 `@import` 链递归内联，共 86 个 CSS 文件
  （tokens → scope → components → decor → arknights → utilities → forced-colors）
- 未包含：`fonts.css`（自托管字体）、`base/`（MediaWiki 正文排版）、`chrome/`（皮肤骨架）、
  `bridge-codex.css`（MediaWiki Codex 令牌桥接）、`img/` 与所有游戏素材
- 代码许可证：MIT，见同目录 `LICENSE`
- 素材版权：上游仓库中的游戏素材归鹰角网络所有，不在 MIT 范围内；本快照未包含任何素材

## 重新生成

```sh
python - <<'PY'
import re, urllib.request
from pathlib import Path
from posixpath import dirname, join, normpath

SHA = '38b02e40eee09d92e2314e234020f825eda75e2b'
BASE = 'https://raw.githubusercontent.com/MooncellWiki/prts-design/%s/packages/css/src/' % SHA
cache, seen = {}, set()

def fetch(rel):
    if rel not in cache:
        cache[rel] = urllib.request.urlopen(BASE + rel).read().decode('utf-8')
    return cache[rel]

IMPORT = re.compile(r'@import\s+url\(["\']?([^"\')]+)["\']?\)\s*;')

def expand(rel):
    if rel in seen:
        return ''
    seen.add(rel)
    return IMPORT.sub(
        lambda m: expand(normpath(join(dirname(rel), m.group(1)))), fetch(rel))

Path('prts-design.css').write_text(expand('standalone.css'), encoding='utf-8')
PY
```

展平产物保留上游的注释与层叠顺序，不做任何规则改写；升级上游时按新提交重跑，
并把本文件里的提交号与抓取日期一并更新。
