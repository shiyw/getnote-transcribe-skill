#!/usr/bin/env bash
set -euo pipefail

[ -x ./runtest.sh ] || {
  echo "缺少可执行的 ./runtest.sh。请写入当前项目真实的测试命令。" >&2
  exit 2
}

out="$(mktemp -t codex-runtest.XXXXXX)"
set +e
./runtest.sh >"$out" 2>&1
status=$?
set -e

if [ "$status" -eq 0 ]; then
  rm -f "$out"
  printf '{}\n'
  exit 0
fi

{
  echo "测试失败。复现命令：./runtest.sh"
  sed -n '1,160p' "$out"
  echo
  echo "退出码：$status"
} >&2

rm -f "$out"
exit 2
