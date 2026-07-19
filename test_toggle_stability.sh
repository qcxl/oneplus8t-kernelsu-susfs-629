#!/bin/bash
# 50轮 toggle 稳定性测试
MAX_ROUNDS=50
PASS=0
FAIL=0
TMPXML="/data/local/tmp/td.xml"
FAIL_MSG=""

echo "=== KSU-Next 开关稳定性测试（50轮）==="
date

adb shell "input keyevent KEYCODE_WAKEUP" 2>/dev/null
adb shell "input touchscreen swipe 540 2300 540 300 500" 2>/dev/null
sleep 3

# 获取所有 toggle switch 的 y 坐标
adb shell "am start -n com.rifsxd.ksunext/.ui.MainActivity" 2>/dev/null > /dev/null
sleep 5
adb shell "uiautomator dump $TMPXML" 2>/dev/null > /dev/null
XML=$(adb shell "cat $TMPXML" 2>/dev/null)

# 提取所有 switch bounds 的 center y
# 格式: bounds="[810,Y1][956,Y2]"
Y_LIST=$(echo "$XML" | grep -o 'bounds="\[810,[0-9]*\]\[956,[0-9]*\]"' | \
    while read -r b; do
        y1=$(echo "$b" | sed 's/.*\[810,\([0-9]*\)\].*/\1/')
        y2=$(echo "$b" | sed 's/.*\[956,\([0-9]*\)\].*/\1/')
        echo $(( (y1 + y2) / 2 ))
    done)

Y_COORDS=()
while IFS= read -r y; do
    [ -n "$y" ] && Y_COORDS+=("$y")
done <<< "$Y_LIST"

echo "发现 ${#Y_COORDS[@]} 个 toggle switch"
[ "${#Y_COORDS[@]}" -eq 0 ] && { echo "❌ 没有 toggle，退出"; exit 1; }

for round in $(seq 1 $MAX_ROUNDS); do
    echo -n "R${round}/$MAX_ROUNDS ... "

    # 开 App → 滑动
    adb shell "am start -n com.rifsxd.ksunext/.ui.MainActivity" 2>/dev/null > /dev/null
    sleep 5
    adb shell "input swipe 500 1800 500 500 200" 2>/dev/null
    sleep 2

    # dump 并读所有 switch 状态
    adb shell "uiautomator dump $TMPXML" 2>/dev/null > /dev/null
    xml=$(adb shell "cat $TMPXML" 2>/dev/null)
    # 提取所有 checked 值（顺序对应 Y_COORDS）
    states=()
    while IFS= read -r line; do
        ch=$(echo "$line" | grep -o 'checked="[a-z]*"' | sed 's/checked="//;s/"//')
        [ -n "$ch" ] && states+=("$ch")
    done < <(echo "$xml" | grep "bounds=\"\[810")

    # 随机选一个 switch 点击
    idx=$(( RANDOM % ${#Y_COORDS[@]} ))
    y=${Y_COORDS[$idx]}
    before=${states[$idx]:-"unknown"}

    adb shell "input tap 883 $y" 2>/dev/null
    sleep 2

    # 读切换后状态
    adb shell "uiautomator dump $TMPXML" 2>/dev/null > /dev/null
    xml=$(adb shell "cat $TMPXML" 2>/dev/null)
    after_states=()
    while IFS= read -r line; do
        ch=$(echo "$line" | grep -o 'checked="[a-z]*"' | sed 's/checked="//;s/"//')
        [ -n "$ch" ] && after_states+=("$ch")
    done < <(echo "$xml" | grep "bounds=\"\[810")
    after=${after_states[$idx]:-"unknown"}

    # 验证切换有效
    if [ "$before" = "$after" ]; then
        echo "❌ S$((idx+1)) 未切换($before)"
        FAIL=$((FAIL + 1))
        FAIL_MSG="$FAIL_MSG\nR${round}: S$((idx+1))未切换($before)"
        adb shell "am force-stop com.rifsxd.ksunext" 2>/dev/null > /dev/null
        sleep 2; continue
    fi

    # 杀进程
    adb shell "am force-stop com.rifsxd.ksunext" 2>/dev/null > /dev/null
    sleep 3

    # 重开验证
    adb shell "am start -n com.rifsxd.ksunext/.ui.MainActivity" 2>/dev/null > /dev/null
    sleep 5
    adb shell "input swipe 500 1800 500 500 200" 2>/dev/null
    sleep 2
    adb shell "uiautomator dump $TMPXML" 2>/dev/null > /dev/null
    xml=$(adb shell "cat $TMPXML" 2>/dev/null)
    rst_states=()
    while IFS= read -r line; do
        ch=$(echo "$line" | grep -o 'checked="[a-z]*"' | sed 's/checked="//;s/"//')
        [ -n "$ch" ] && rst_states+=("$ch")
    done < <(echo "$xml" | grep "bounds=\"\[810")
    restart=${rst_states[$idx]:-"missing"}

    if [ "$restart" = "$after" ]; then
        echo "✅ S$((idx+1)): $before→$after, 重启保持"
        PASS=$((PASS + 1))
    else
        echo "❌ S$((idx+1)): 切后=$after 重启=$restart"
        FAIL=$((FAIL + 1))
        FAIL_MSG="$FAIL_MSG\nR${round}: S$((idx+1))重启状态异常(切后$after,重启$restart)"
    fi
    sleep 2
done

echo ""
echo "================================"
echo "总轮次: $MAX_ROUNDS | 通过: $PASS | 失败: $FAIL"
[ -n "$FAIL_MSG" ] && echo -e "失败:$FAIL_MSG"
date