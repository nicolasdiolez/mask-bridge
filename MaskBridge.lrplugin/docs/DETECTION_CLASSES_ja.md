# Mask Bridge - 検出クラス

RF-DETR は、COCO データセットから **80 個のオブジェクトクラス** を検出します。ここでは、詳細設定で使用できる完全なリストを示します。

⚠️ **重要:** AI エンジンはこれらの英語の用語を使用します。したがって、プラグインには元の用語 (英語) を入力する必要があります。

---

## 🚗 交通・乗り物 (9 クラス)

| クラス (英語) | 翻訳 / キーワード |
|---------------|-------------------|
| person | 人、人間 |
| bicycle | 自転車 |
| car | 車、自動車 |
| motorcycle | オートバイ、バイク |
| airplane | 飛行機 |
| bus | バス |
| train | 電車、列車 |
| truck | トラック |
| boat | ボート、船 |

---

## 🐾 動物 (10 クラス)

| クラス (英語) | 翻訳 / キーワード |
|---------------|-------------------|
| bird | 鳥 |
| cat | 猫 |
| dog | 犬 |
| horse | 馬 |
| sheep | 羊 |
| cow | 牛 |
| elephant | 象 |
| bear | 熊 |
| zebra | シマウマ |
| giraffe | キリン |

---

## 🪑 家具・インテリア (6 クラス)

| クラス (英語) | 翻訳 / キーワード |
|---------------|-------------------|
| bench | ベンチ |
| chair | 椅子 |
| couch | ソファ |
| bed | ベッド |
| dining table | ダイニングテーブル |
| toilet | トイレ |

---

## 📺 電子機器 (8 クラス)

| クラス (英語) | 翻訳 / キーワード |
|---------------|-------------------|
| tv | テレビ |
| laptop | ノートパソコン、ラップトップ |
| mouse | マウス |
| remote | リモコン |
| keyboard | キーボード |
| cell phone | 携帯電話、スマートフォン |
| microwave | 電子レンジ |
| oven | オーブン |

---

## 🎒 アクセサリー・小物 (6 クラス)

| クラス (英語) | 翻訳 / キーワード |
|---------------|-------------------|
| backpack | バックパック、リュックサック |
| umbrella | 傘 |
| handbag | ハンドバッグ |
| tie | ネクタイ |
| suitcase | スーツケース |
| frisbee | フリスビー |

---

## ⚽ スポーツ・レジャー (9 クラス)

| クラス (英語) | 翻訳 / キーワード |
|---------------|-------------------|
| skis | スキー板 |
| snowboard | スノーボード |
| sports ball | ボール、スポーツボール |
| kite | 凧 |
| baseball bat | 野球のバット |
| baseball glove | 野球のグローブ |
| skateboard | スケートボード |
| surfboard | サーフボード |
| tennis racket | テニスラケット |

---

## 🍎 食べ物 (17 クラス)

| クラス (英語) | 翻訳 / キーワード |
|---------------|-------------------|
| bottle | ボトル、瓶 |
| wine glass | ワイングラス |
| cup | カップ、コップ |
| fork | フォーク |
| knife | ナイフ |
| spoon | スプーン |
| bowl | ボウル、茶碗 |
| banana | バナナ |
| apple | りんご |
| sandwich | サンドイッチ |
| orange | オレンジ |
| broccoli | ブロッコリー |
| carrot | 人参 |
| hot dog | ホットドッグ |
| pizza | ピザ |
| donut | ドーナツ |
| cake | ケーキ |

---

## 🏠 その他のオブジェクト (15 クラス)

| クラス (英語) | 翻訳 / キーワード |
|---------------|-------------------|
| traffic light | 信号機 |
| fire hydrant | 消火栓 |
| stop sign | 止まれの標識 |
| parking meter | パーキングメーター |
| potted plant | 鉢植えの植物 |
| toaster | トースター |
| sink | シンク、流し台 |
| refrigerator | 冷蔵庫 |
| book | 本 |
| clock | 時計 |
| vase | 花瓶 |
| scissors | ハサミ |
| teddy bear | テディベア、ぬいぐるみ |
| hair drier | ヘアドライヤー |
| toothbrush | 歯ブラシ |

---

## ⚠️ 制限事項

**RF-DETR では検出できません：**
- ケーブル / 配線
- 建物 / 家
- 木 (「potted plant」を除く)
- 空 / 雲
- 道路 / 歩道
- 山 / 風景

---

## 💡 Mask Bridge での使いかた

**詳細設定** セクションでは、クラスを英語でカンマ区切りで入力します：

```
person, car, dog
```

### 🧠 スマートカテゴリー（マクロ）
これらの一般的な用語を使用して、複数のクラスを一度に選択できます：

| キーワード | 検出対象 |
|------------|----------|
| **vehicle** | car, motorcycle, bus, train, truck |
| **animal** | bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe |
| **furniture** | chair, couch, bed, dining table, bench, toilet |
| **electronics** | tv, laptop, mouse, remote, keyboard, phone |
| **sports** | すべてのスポーツ用品 + skateboard, surfboard, tennis racket |
| **plant** | potted plant (植物) |
