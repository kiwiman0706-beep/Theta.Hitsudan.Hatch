// 筆談・翻訳 患者側表示 — M5PaperS3 用ファームウェア（USBシリアル版）
//
// PCで描いた白黒画像(1bpp)を受け取り、電子ペーパーに出すだけの「受け身」の端末。
// 文字の描画はPC側で行うので、端末にフォントを持たせる必要はない。
// 画面下の返答ボタンが押されたら、その座標を "TOUCH x y" でPCに返す（ボタンの判定はPC側）。
//
// ビルド: Arduino IDE 2.x
//   ボードマネージャ: "esp32 by Espressif"（3.x）、ボード: "M5PaperS3"（無ければ "ESP32S3 Dev Module"）
//   ライブラリ: M5Unified, M5GFX（ライブラリマネージャから）
//   ツール設定: USB CDC On Boot = Enabled / PSRAM = OPI PSRAM
//
// フレーム形式は app/serial_display.py の説明を参照。

#include <M5Unified.h>

static const uint8_t MAGIC[4] = {'H', 'T', 'D', 'N'};
static const uint8_t TYPE_IMAGE = 1;
static const uint8_t TYPE_CLEAR = 2;
static const size_t HEADER_LEN = 4 + 1 + 2 + 2 + 4;
static const uint32_t MAX_PAYLOAD = 960 * 540 / 8;  // 1bpp 全画面
static const uint32_t BYTE_TIMEOUT_MS = 2000;       // フレーム途中で途切れたら破棄

enum State { WAIT_MAGIC, READ_HEADER, READ_PAYLOAD, READ_CRC };

static State state = WAIT_MAGIC;
static uint8_t header[HEADER_LEN];
static size_t got = 0;
static uint8_t* payload = nullptr;
static uint8_t crcBuf[4];
static uint8_t kind = 0;
static uint16_t imgW = 0, imgH = 0;
static uint32_t payloadLen = 0;
static uint32_t lastByteMs = 0;
static bool showingMessage = false;

static uint32_t crc32(const uint8_t* data, size_t len) {
  uint32_t crc = 0xFFFFFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int b = 0; b < 8; b++) crc = (crc >> 1) ^ (0xEDB88320 & (-(int32_t)(crc & 1)));
  }
  return ~crc;
}

static uint32_t le32(const uint8_t* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }
static uint16_t le16(const uint8_t* p) { return p[0] | (p[1] << 8); }

static void drawIdle() {
  M5.Display.setEpdMode(epd_mode_t::epd_quality);
  M5.Display.fillScreen(TFT_WHITE);
  M5.Display.setTextColor(TFT_LIGHTGREY, TFT_WHITE);
  M5.Display.setFont(&fonts::FreeSansBold24pt7b);
  M5.Display.setTextDatum(middle_center);
  M5.Display.drawString("-", M5.Display.width() / 2, M5.Display.height() / 2);
  M5.Display.display();
  showingMessage = false;
}

static void handleFrame() {
  if (kind == TYPE_CLEAR) {
    drawIdle();
    Serial.println("OK");
    return;
  }
  if (kind != TYPE_IMAGE) {
    Serial.println("ERR kind");
    return;
  }
  if (imgW > M5.Display.width() || imgH > M5.Display.height()) {
    Serial.println("ERR size");
    return;
  }
  M5.Display.setEpdMode(epd_mode_t::epd_quality);  // 残像を残さない全面書き換え
  M5.Display.startWrite();
  M5.Display.fillScreen(TFT_WHITE);
  M5.Display.drawBitmap(0, 0, payload, imgW, imgH, TFT_BLACK, TFT_WHITE);
  M5.Display.endWrite();
  M5.Display.display();
  showingMessage = true;
  Serial.println("OK");
}

static void resetParser() {
  state = WAIT_MAGIC;
  got = 0;
}

static void feed(uint8_t c) {
  switch (state) {
    case WAIT_MAGIC:
      if (c == MAGIC[got]) {
        header[got++] = c;
        if (got == 4) state = READ_HEADER;
      } else {
        got = (c == MAGIC[0]) ? 1 : 0;
        if (got) header[0] = c;
      }
      break;
    case READ_HEADER:
      header[got++] = c;
      if (got == HEADER_LEN) {
        kind = header[4];
        imgW = le16(header + 5);
        imgH = le16(header + 7);
        payloadLen = le32(header + 9);
        if (payloadLen > MAX_PAYLOAD || (kind == TYPE_IMAGE && payloadLen != (uint32_t)((imgW + 7) / 8) * imgH)) {
          Serial.println("ERR length");
          resetParser();
          return;
        }
        got = 0;
        state = payloadLen ? READ_PAYLOAD : READ_CRC;
      }
      break;
    case READ_PAYLOAD:
      payload[got++] = c;
      if (got == payloadLen) {
        got = 0;
        state = READ_CRC;
      }
      break;
    case READ_CRC:
      crcBuf[got++] = c;
      if (got == 4) {
        if (le32(crcBuf) == crc32(payload, payloadLen)) {
          handleFrame();
        } else {
          Serial.println("ERR crc");
        }
        resetParser();
      }
      break;
  }
}

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  if (M5.Display.width() < M5.Display.height()) {
    M5.Display.setRotation(M5.Display.getRotation() ^ 1);  // 横置き 960x540
  }
  Serial.setRxBufferSize(16384);
  Serial.begin(921600);  // USB CDC なので実際の速度はボーレートに依存しない
  payload = (uint8_t*)ps_malloc(MAX_PAYLOAD);
  if (!payload) payload = (uint8_t*)malloc(MAX_PAYLOAD);
  drawIdle();
  Serial.println("READY");
}

void loop() {
  M5.update();

  while (Serial.available()) {
    feed((uint8_t)Serial.read());
    lastByteMs = millis();
  }
  if (state != WAIT_MAGIC && millis() - lastByteMs > BYTE_TIMEOUT_MS) {
    Serial.println("ERR timeout");
    resetParser();
  }

  if (showingMessage && M5.Touch.getCount()) {
    auto t = M5.Touch.getDetail();
    if (t.wasPressed()) {
      Serial.printf("TOUCH %d %d\n", t.x, t.y);
    }
  }
  delay(1);
}
