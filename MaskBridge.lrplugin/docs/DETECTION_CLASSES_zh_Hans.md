# Mask Bridge - 检测类别

RF-DETR 从 COCO 数据集中检测 **80 种对象类别**。以下是可在高级设置中使用的完整列表。

⚠️ **重要提示：** AI 引擎使用这些英文术语。因此，您必须在插件中输入原始的英文术语。

---

## 🚗 交通工具 (9 种类)

| 类别 (英文) | 翻译 / 关键词 |
|-------------|---------------|
| person | 人类，人 |
| bicycle | 自行车 |
| car | 汽车，小汽车 |
| motorcycle | 摩托车 |
| airplane | 飞机 |
| bus | 公交车，巴士 |
| train | 火车，列车 |
| truck | 卡车 |
| boat | 船，小船 |

---

## 🐾 动物 (10 种类)

| 类别 (英文) | 翻译 / 关键词 |
|-------------|---------------|
| bird | 鸟 |
| cat | 猫 |
| dog | 狗 |
| horse | 马 |
| sheep | 羊，绵羊 |
| cow | 牛，奶牛 |
| elephant | 大象 |
| bear | 熊 |
| zebra | 斑马 |
| giraffe | 长颈鹿 |

---

## 🪑 家具与室内 (6 种类)

| 类别 (英文) | 翻译 / 关键词 |
|-------------|---------------|
| bench | 长凳 |
| chair | 椅子 |
| couch | 沙发 |
| bed | 床 |
| dining table | 餐桌 |
| toilet | 厕所，马桶 |

---

## 📺 电子产品 (8 种类)

| 类别 (英文) | 翻译 / 关键词 |
|-------------|---------------|
| tv | 电视 |
| laptop | 笔记本电脑 |
| mouse | 鼠标 |
| remote | 遥控器 |
| keyboard | 键盘 |
| cell phone | 手机，移动电话 |
| microwave | 微波炉 |
| oven | 烤箱 |

---

## 🎒 配饰 (6 种类)

| 类别 (英文) | 翻译 / 关键词 |
|-------------|---------------|
| backpack | 背包 |
| umbrella | 雨伞 |
| handbag | 手提包 |
| tie | 领带 |
| suitcase | 行李箱 |
| frisbee | 飞盘 |

---

## ⚽ 运动与休闲 (9 种类)

| 类别 (英文) | 翻译 / 关键词 |
|-------------|---------------|
| skis | 滑雪板 (双板) |
| snowboard | 单板滑雪板 |
| sports ball | 运动球 |
| kite | 风筝 |
| baseball bat | 棒球棒 |
| baseball glove | 棒球手套 |
| skateboard | 滑板 |
| surfboard | 冲浪板 |
| tennis racket | 网球拍 |

---

## 🍎 食物 (17 种类)

| 类别 (英文) | 翻译 / 关键词 |
|-------------|---------------|
| bottle | 瓶子 |
| wine glass | 高脚杯，葡萄酒杯 |
| cup | 杯子 |
| fork | 叉子 |
| knife | 刀 |
| spoon | 勺子 |
| bowl | 碗 |
| banana | 香蕉 |
| apple | 苹果 |
| sandwich | 三明治 |
| orange | 橙子 |
| broccoli | 西兰花 |
| carrot | 胡萝卜 |
| hot dog | 热狗 |
| pizza | 比萨饼，披萨 |
| donut | 甜甜圈 |
| cake | 蛋糕 |

---

## 🏠 其他物品 (15 种类)

| 类别 (英文) | 翻译 / 关键词 |
|-------------|---------------|
| traffic light | 红绿灯，交通灯 |
| fire hydrant | 消防栓 |
| stop sign | 停车标志 |
| parking meter | 停车计费表 |
| potted plant | 盆栽植物 |
| toaster | 烤面包机 |
| sink | 水槽，洗手池 |
| refrigerator | 冰箱 |
| book | 书 |
| clock | 钟表，时钟 |
| vase | 花瓶 |
| scissors | 剪刀 |
| teddy bear | 泰迪熊 |
| hair drier | 吹风机 |
| toothbrush | 牙刷 |

---

## ⚠️ 限制

**RF-DETR 无法检测：**
- 电缆 / 电线
- 建筑物 / 房屋
- 树木（除了 "potted plant" 盆栽）
- 天空 / 云朵
- 道路 / 人行道
- 山脉 / 风景

---

## 💡 在 Mask Bridge 中的使用

在 **高级设置 (Advanced Settings)** 部分中，输入用逗号分隔的英文类别：

```
person, car, dog
```

### 🧠 智能类别（宏）
您可以使用这些通用术语一次选择多个类别：

| 关键词 | 检测内容 |
|--------|----------|
| **vehicle** | car, motorcycle, bus, train, truck |
| **animal** | bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe |
| **furniture** | chair, couch, bed, dining table, bench, toilet |
| **electronics** | tv, laptop, mouse, remote, keyboard, phone |
| **sports** | 所有运动装备 + skateboard, surfboard, tennis racket |
| **plant** | potted plant (植被植物) |
