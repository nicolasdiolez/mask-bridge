# Mask Bridge - Classes de Detecção

O RF-DETR detecta **80 classes de objetos** do conjunto de dados COCO. Aqui está a lista completa que você pode usar nas Configurações Avançadas.

⚠️ **Importante:** O mecanismo de IA usa esses termos em inglês. Portanto, você deve inserir os termos originais (em inglês) no plugin.

---

## 🚗 Transporte (9 classes)

| Classe (inglês) | Tradução / Palavras-chave |
|-----------------|---------------------------|
| person | pessoa, humano |
| bicycle | bicicleta, bike |
| car | carro, automóvel |
| motorcycle | motocicleta, moto |
| airplane | avião |
| bus | ônibus |
| train | trem |
| truck | caminhão |
| boat | barco |

---

## 🐾 Animais (10 classes)

| Classe (inglês) | Tradução / Palavras-chave |
|-----------------|---------------------------|
| bird | pássaro, ave |
| cat | gato |
| dog | cachorro, cão |
| horse | cavalo |
| sheep | ovelha |
| cow | vaca |
| elephant | elefante |
| bear | urso |
| zebra | zebra |
| giraffe | girafa |

---

## 🪑 Móveis e Interior (6 classes)

| Classe (inglês) | Tradução / Palavras-chave |
|-----------------|---------------------------|
| bench | banco |
| chair | cadeira |
| couch | sofá |
| bed | cama |
| dining table | mesa de jantar |
| toilet | vaso sanitário, banheiro |

---

## 📺 Eletrônicos (8 classes)

| Classe (inglês) | Tradução / Palavras-chave |
|-----------------|---------------------------|
| tv | televisão, tv |
| laptop | notebook, laptop |
| mouse | mouse |
| remote | controle remoto |
| keyboard | teclado |
| cell phone | celular, telefone |
| microwave | micro-ondas |
| oven | forno |

---

## 🎒 Acessórios (6 classes)

| Classe (inglês) | Tradução / Palavras-chave |
|-----------------|---------------------------|
| backpack | mochila |
| umbrella | guarda-chuva |
| handbag | bolsa |
| tie | gravata |
| suitcase | mala, bagagem |
| frisbee | frisbee |

---

## ⚽ Esportes e Lazer (9 classes)

| Classe (inglês) | Tradução / Palavras-chave |
|-----------------|---------------------------|
| skis | esquis |
| snowboard | snowboard |
| sports ball | bola, bola de esportes |
| kite | pipa |
| baseball bat | taco de beisebol |
| baseball glove | luva de beisebol |
| skateboard | skate |
| surfboard | prancha de surfe |
| tennis racket | raquete de tênis |

---

## 🍎 Comida (17 classes)

| Classe (inglês) | Tradução / Palavras-chave |
|-----------------|---------------------------|
| bottle | garrafa |
| wine glass | taça de vinho |
| cup | copo, xícara |
| fork | garfo |
| knife | faca |
| spoon | colher |
| bowl | tigela, bacia |
| banana | banana |
| apple | maçã |
| sandwich | sanduíche |
| orange | laranja |
| broccoli | brócolis |
| carrot | cenoura |
| hot dog | cachorro-quente |
| pizza | pizza |
| donut | donut, rosquinha |
| cake | bolo |

---

## 🏠 Outros Objetos (15 classes)

| Classe (inglês) | Tradução / Palavras-chave |
|-----------------|---------------------------|
| traffic light | semáforo |
| fire hydrant | hidrante |
| stop sign | placa de pare |
| parking meter | parquímetro |
| potted plant | planta em vaso |
| toaster | torradeira |
| sink | pia |
| refrigerator | geladeira, refrigerador |
| book | livro |
| clock | relógio |
| vase | vaso |
| scissors | tesoura |
| teddy bear | urso de pelúcia |
| hair drier | secador de cabelo |
| toothbrush | escova de dentes |

---

## ⚠️ Limitações

**NÃO detectável pelo RF-DETR:**
- Cabos / fios
- Edifícios / casas
- Árvores (exceto "potted plant")
- Céus / nuvens
- Estradas / calçadas
- Montanhas / paisagens

---

## 💡 Uso no Mask Bridge

Na seção **Configurações Avançadas**, digite as classes em inglês separadas por vírgulas:

```
person, car, dog
```

### 🧠 Categorias Inteligentes (Macro)
Você pode usar esses termos genéricos para selecionar várias classes de uma vez:

| Palavra-chave | Detecta |
|---------------|---------|
| **vehicle** | car, motorcycle, bus, train, truck |
| **animal** | bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe |
| **furniture** | chair, couch, bed, dining table, bench, toilet |
| **electronics** | tv, laptop, mouse, remote, keyboard, phone |
| **sports** | todo o equipamento esportivo + skateboard, surfboard, tennis racket |
| **plant** | potted plant (vegetação) |
