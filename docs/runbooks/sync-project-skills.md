# 同步项目 Skills

## 适用场景

- 在新设备克隆 Loot 后安装项目级 Codex skills。
- 项目内 skill 更新后刷新本机 `$CODEX_HOME/skills` 镜像。
- 比较项目权威副本与本机安装版本是否一致。

## 权威来源

```text
docs/skills/vibe-context-manager/SKILL.md
```

本机默认安装位置：

```text
${CODEX_HOME:-$HOME/.codex}/skills/vibe-context-manager/SKILL.md
```

## Windows PowerShell

在项目根目录执行：

```powershell
$codexHome = if ($env:CODEX_HOME) {
    $env:CODEX_HOME
} else {
    Join-Path $HOME '.codex'
}
$source = Join-Path $PWD 'docs\skills\vibe-context-manager\SKILL.md'
$targetDir = Join-Path $codexHome 'skills\vibe-context-manager'
$target = Join-Path $targetDir 'SKILL.md'

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
Copy-Item -LiteralPath $source -Destination $target -Force
Get-FileHash -Algorithm SHA256 $source, $target
```

两个 SHA-256 必须相同。

项目副本校验：

```powershell
$validator = Join-Path $codexHome 'skills\.system\skill-creator\scripts\quick_validate.py'
$env:PYTHONUTF8 = '1'
py -3.12 $validator 'docs\skills\vibe-context-manager'
```

`PYTHONUTF8=1` 用于避免 Windows 默认 GBK 解码 UTF-8 skill 时产生误报。

## macOS / Linux

在项目根目录执行：

```bash
codex_home="${CODEX_HOME:-$HOME/.codex}"
source_file="docs/skills/vibe-context-manager/SKILL.md"
target_dir="$codex_home/skills/vibe-context-manager"

mkdir -p "$target_dir"
cp "$source_file" "$target_dir/SKILL.md"
sha256sum "$source_file" "$target_dir/SKILL.md"
```

如果系统使用 `shasum`，将最后一行改为：

```bash
shasum -a 256 "$source_file" "$target_dir/SKILL.md"
```

项目副本校验：

```bash
python3 "$codex_home/skills/.system/skill-creator/scripts/quick_validate.py" \
  "docs/skills/vibe-context-manager"
```

## 更新流程

1. 只修改项目内 `docs/skills/vibe-context-manager/SKILL.md`。
2. 使用 skill validator 校验项目副本。
3. 执行本 runbook，同步并核对哈希。
4. 更新相关 AGENTS、文档索引或过程记录。
5. 提交并 push；其他设备 pull 后再次执行本 runbook。

不要从本机安装目录反向覆盖项目副本，除非已经确认本机版本才是有意保留的新版本。
