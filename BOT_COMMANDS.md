# 🤖 Crypto Bot - Danh Sách Lệnh

## 📊 Phân Tích & Tín Hiệu

| Lệnh                 | Mô tả                                               |
| -------------------- | --------------------------------------------------- |
| `BTC` (gõ tên token) | Báo cáo tổng hợp (Spot + Futures + Tin tức)         |
| `/spot BTC`          | Tín hiệu MUA Spot (4h + 1d, TP +5/10/20%)           |
| `/futures ETH`       | Tín hiệu Long/Short Futures (tất cả TF, TP +2/4/7%) |
| `/signals`           | Xem tín hiệu đang theo dõi TP/SL                    |
| `/scan`              | Quét nhanh BTC, ETH, SOL                            |
| `/news`              | Tin tức crypto mới nhất                             |
| `/fng` hoặc `/fear`  | Chỉ số Tham lam & Sợ hãi (Fear & Greed Index)       |

> ⏱ Sau khi dùng `/spot` hoặc `/futures`, bot tự giám sát giá mỗi 15s và thông báo TP1/TP2/TP3/SL.

---

## 💎 DEX Gem Scanner

| Lệnh               | Mô tả                                    |
| ------------------ | ---------------------------------------- |
| `/gem`             | Tìm gem tiềm năng x100 trên Solana       |
| `/gem ethereum`    | Tìm gem trên Ethereum                    |
| `/gem base`        | Tìm gem trên Base                        |
| `/check PEPE`      | Phân tích sâu token (Safety + GEM Score) |
| `/check 0x6982...` | Phân tích bằng contract address          |

> 📋 Mỗi kèo đều có **Contract Address** (bấm copy) và **tên token** là link DexScreener.

---

## 🛒 Mua Token Trực Tiếp

| Lệnh                   | Mô tả                              |
| ---------------------- | ---------------------------------- |
| `/buy [CA] [số ETH]`   | Mua token trên Arbitrum (mặc định) |
| `/buy [CA] [số] base`  | Mua trên Base                      |
| `/buy [CA] [số] bsc 2` | Mua trên BSC bằng ví #2            |

**Ví dụ:**

```
/buy 0x6982...abc 0.001
/buy 0x6982...abc 0.002 base
/buy 0x6982...abc 0.001 arbitrum 2
```

> ⚠️ Cần nạp gas (ETH/BNB) vào ví trước. Dùng `/balance` kiểm tra.

---

## 🚨 CEX Listing Scanner

| Lệnh       | Mô tả                                              |
| ---------- | -------------------------------------------------- |
| `/listing` | Tìm token sắp lên Binance (so sánh Gate.io + MEXC) |
| `/monitor` | Bật/Tắt giám sát listing mới mỗi 5 phút            |

> 🔥 Token có trên Gate.io + MEXC nhưng chưa Binance = khả năng listing cao → mua sớm trên DEX!

---

## 💼 Quản Lý Ví (Airdrop)

| Lệnh                | Mô tả                          |
| ------------------- | ------------------------------ |
| `/wallet`           | Tạo 1 ví EVM mới               |
| `/wallet 10`        | Tạo 10 ví cùng lúc (tối đa 20) |
| `/wallets`          | Xem danh sách tất cả ví        |
| `/balance`          | Kiểm tra số dư Ethereum        |
| `/balance arbitrum` | Kiểm tra số dư Arbitrum        |
| `/networks`         | Xem 8 mạng EVM hỗ trợ          |

---

## 🎯 Farming Airdrop

| Lệnh                    | Mô tả                                |
| ----------------------- | ------------------------------------ |
| `/farm`                 | Farm trên Arbitrum (swap tạo volume) |
| `/farm base`            | Farm trên Base                       |
| `/claim 0x... ethereum` | Claim airdrop từ contract            |

---

## ⚙️ Hệ Thống

| Lệnh     | Mô tả              |
| -------- | ------------------ |
| `/start` | Bắt đầu + xem menu |
| `/menu`  | Hiện menu đầy đủ   |

---

## 🔗 Mạng Hỗ Trợ

Ethereum, BSC, Polygon, Arbitrum, Base, zkSync Era, Scroll, Optimism

---

## 📈 Paper Trading

| Lệnh | Mô tả |
| ---- | ----- |
| `/paper` | Xem tổng quan tài khoản ảo (balance, PnL, lệnh đang mở) |
| `/autotrade on` | Bật tự động vào lệnh theo tín hiệu AI |
| `/autotrade off` | Tắt tự động vào lệnh |
| `/trailsl BTC on` | Bật Trailing Stop Loss cho lệnh BTC đang mở |
| `/trailsl BTC off` | Tắt Trailing Stop Loss |

> 💡 **Trailing SL:** Khi giá chạm TP1 → SL tự dịch lên break-even. Khi chạm TP2 → SL dịch lên TP1.

---

## 🔔 Price Alerts *(MỚI)*

| Lệnh | Mô tả |
| ---- | ----- |
| `/alert BTC 100000 above` | Cảnh báo khi BTC vượt $100,000 |
| `/alert ETH 2000 below` | Cảnh báo khi ETH xuống dưới $2,000 |
| `/alerts` | Xem danh sách alerts đang active |
| `/alerts del 3` | Xóa alert #3 |

> 🔔 Alert tự động tắt sau khi kích hoạt 1 lần. Đặt lại nếu muốn tiếp tục theo dõi.

---

## 🔐 Bảo Mật

| Lệnh | Mô tả |
| ---- | ----- |
| `/security` | Xem trạng thái bảo mật hiện tại |
| `/setpin [mã]` | Đặt PIN bảo vệ lệnh nhạy cảm |
| `/pin [mã]` | Xác nhận PIN (hiệu lực 15 phút) |
| `/whitelist [chat_id]` | Thêm Chat ID vào danh sách trắng |
| `/setlimit [ETH/tx] [ETH/ngày]` | Đặt giới hạn giao dịch |
| `/audit` | Xem 20 hành động gần nhất |

---

## 🌐 Social Automation

| Lệnh | Mô tả |
| ---- | ----- |
| `/social` | Xem trạng thái Telegram + Twitter bots |
| `/claimall [bot] [lệnh]` | Điều phối tất cả Tele acc gửi lệnh tap-to-earn |
| `/retweet [tweet_id]` | X-Raid: like + retweet hàng loạt |

---

## 🪂 CEX Airdrop

| Lệnh | Mô tả |
| ---- | ----- |
| `/freeairdrop` | Xem danh sách airdrop miễn phí từ Binance/Bybit/OKX |

---

## Flow Sử Dụng

### Trading:

```
Gõ BTC → xem báo cáo → /spot BTC hoặc /futures BTC → bot theo dõi TP/SL tự động
```

### Tìm Gem:

```
/gem → xem top gem → /check [tên] → phân tích → /buy [CA] 0.001 → mua luôn
```

### Listing:

```
/listing → tìm token sắp lên Binance → /check [token] → /buy [CA] 0.001
```

### Airdrop:

```
/wallet 10 → tạo ví → /farm arbitrum → tạo volume → /claim 0x... → claim token
```

### Paper Trading với Trailing SL:

```
/autotrade on → bot tự vào lệnh → /paper → xem lệnh → /trailsl BTC on → SL tự dịch lên khi lời
```

### Price Alert:

```
/alert BTC 100000 above → đặt cảnh báo → bot thông báo khi BTC vượt $100k
/alerts → xem danh sách → /alerts del 1 → xóa alert #1
```
