# 校準驗證報告（C8 評審團 vs gold）

- gold 列數：117；實際可比對：115；缺分/未評分：2
- judge：`llm-jury@cd50a7e9`
- 門檻：accuracy ≥ 0.80（C5）

| 面向 | accuracy | 常數ND baseline | macro-F1 | n | 判定 |
| --- | --- | --- | --- | --- | --- |
| overall | 0.8174 | 0.0000 | 0.5706 | 115 | ✅ |
| quality | 0.7652 | 0.7565 | 0.4698 | 115 | ❌ |
| speed | 0.9652 | 0.9391 | 0.5953 | 115 | ✅ |
| tokenEfficiency | 0.9739 | 0.9913 | 0.2478 | 115 | ✅ |
| tokenUsage | 0.9913 | 0.9826 | 0.5556 | 115 | ✅ |
| priceValue | 0.9739 | 0.9217 | 0.6797 | 115 | ✅ |

### overall 混淆矩陣（列=gold，欄=評審團）

| gold＼pred | positive | negative | neutral | __no_answer__ |
| --- | --- | --- | --- | --- |
| positive | 9 | 0 | 1 | 2 |
| negative | 0 | 7 | 1 | 1 |
| neutral | 11 | 1 | 78 | 4 |
| __no_answer__ | 0 | 0 | 0 | 0 |

### overall 來源切片

- hn: n=49, accuracy=0.8776
- reddit: n=32, accuracy=0.7812
- x: n=34, accuracy=0.7647

## 總判定：❌ 有面向未達 0.80

> 注意：gold 由四家真實 LLM（qwen3.8-flash／mimo-v2.6-flash／minimax-m3／
> nemotron-3.5-lightning）逐則 API 標註、≥3/4 多數成 gold，無人類 ground truth。
> 評審團 prob 只有 {1.0, 0.75} 兩個值，ECE 僅供參考。
