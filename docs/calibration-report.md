# 校準驗證報告（C8 評審團 vs gold）

- gold 列數：117；實際可比對：115；缺分/未評分：2
- judge：`llm-jury@cd50a7e9`
- 門檻（owner 裁定 2026-09-30）：overall ≥ 0.80；五面向改為「accuracy 須勝過常數 not-discussed baseline」，且「有討論的列數」< 10 的面向標『樣本不足』（一兩列之差純屬雜訊，不得據以下結論），呈現時須標註面向可信度。

| 面向 | accuracy | 常數ND baseline | 有討論n | macro-F1 | n | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| overall | 0.8174 | 0.0000 | 115 | 0.5706 | 115 | ✅ |
| quality | 0.7652 | 0.7565 | 28 | 0.4698 | 115 | ✅ 勝過 baseline |
| speed | 0.9652 | 0.9391 | 7 | 0.5953 | 115 | ⚠️ 樣本不足 |
| tokenEfficiency | 0.9739 | 0.9913 | 1 | 0.2478 | 115 | ⚠️ 樣本不足 |
| tokenUsage | 0.9913 | 0.9826 | 2 | 0.5556 | 115 | ⚠️ 樣本不足 |
| priceValue | 0.9739 | 0.9217 | 9 | 0.6797 | 115 | ⚠️ 樣本不足 |

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

## 總判定：✅ 過關（overall ≥ 0.80，各面向勝過或持平於常數 baseline）

> 注意：gold 由四家真實 LLM（qwen3.8-flash／mimo-v2.6-flash／minimax-m3／
> nemotron-3.5-lightning）逐則 API 標註、≥3/4 多數成 gold，無人類 ground truth。
> 評審團 prob 只有 {1.0, 0.75} 兩個值，ECE 僅供參考。
> 「有討論 n」過小的面向（<10）無法有意義地評比，呈現時必須標註可信度不足。
