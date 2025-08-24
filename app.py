import os, time, json, random, io
from datetime import datetime
from dotenv import load_dotenv
import requests

# --- OpenAI SDK (Responses, Audio Transcribe, TTS) ---
from openai import OpenAI

# --- Optional alerts ---
from twilio.rest import Client as TwilioClient

# --- Optional auto-photo capture ---
import cv2

load_dotenv()

# --- Config ---
LANGUAGE = "te"  # 'hi' for Hindi, 'te' Telugu, 'ta' Tamil, etc.
VILLAGE_NAME = "Kondapalli"
STATE = "Andhra Pradesh"
USE_WHATSAPP = bool(os.getenv("TWILIO_ACCOUNT_SID"))
CAPTURE_PHOTO_ON_RISK = True

# --- Keys ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")  # Optional
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Twilio (optional) ---
twilio = None
if USE_WHATSAPP:
    twilio = TwilioClient(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    TW_FROM_WA = os.getenv("TWILIO_FROM_WHATSAPP")
    TO_WA = os.getenv("TO_WHATSAPP")
    TW_FROM_SMS = os.getenv("TWILIO_FROM_SMS")
    TO_SMS = os.getenv("TO_SMS")

# -------------------------------
# 1) IoT sensor ingestion (simulate now)
# -------------------------------
def read_iot_sensors():
    """
    Replace this stub with real sensor reads (e.g., over serial/MQTT):
      - temperature_c, humidity_pct, soil_moisture_pct, wind_speed_ms
    """
    return {
        "temperature_c": round(random.uniform(24.0, 36.0), 1),
        "humidity_pct": round(random.uniform(45, 95), 0),
        "soil_moisture_pct": round(random.uniform(20, 90), 0),
        "wind_speed_ms": round(random.uniform(0.5, 18.0), 1)
    }

# -------------------------------
# 2) Weather forecast (stub/OpenWeather example)
# -------------------------------
def get_weather_forecast(lat=16.521, lon=80.63):
    """
    Replace this with IMD/NASA/your source. Here we show OpenWeather as an example.
    Return a compact dict your AI can read easily.
    """
    if not OPENWEATHER_API_KEY:
        # Fallback: simulated forecast
        return {
            "source": "simulated",
            "next_12h": {"rain_mm": round(random.uniform(0, 50), 1),
                         "wind_ms": round(random.uniform(1, 20), 1),
                         "conditions": random.choice(["clear", "clouds", "rain", "thunderstorm"])},
            "next_3d": [{"day": 1, "rain_mm": round(random.uniform(0, 80), 1), "wind_ms": round(random.uniform(1, 20), 1)},
                        {"day": 2, "rain_mm": round(random.uniform(0, 80), 1), "wind_ms": round(random.uniform(1, 20), 1)},
                        {"day": 3, "rain_mm": round(random.uniform(0, 80), 1), "wind_ms": round(random.uniform(1, 20), 1)}]
        }

    url = ("https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}"
           "&appid={key}&units=metric").format(lat=lat, lon=lon, key=OPENWEATHER_API_KEY)
    r = requests.get(url, timeout=15)
    data = r.json()

    # Very compact extraction for demo (next 12h & 3 days, coarse)
    rain_12h = 0.0
    max_wind_12h = 0.0
    condition_12h = "clear"
    for item in data.get("list", [])[:4]:  # 4 * 3h = 12 hours
        rain_12h += item.get("rain", {}).get("3h", 0.0)
        wind = item.get("wind", {}).get("speed", 0.0)
        if wind > max_wind_12h:
            max_wind_12h = wind
        weather_main = item.get("weather", [{}])[0].get("main", "").lower()
        if weather_main in ["thunderstorm", "rain", "drizzle", "clouds"]:
            condition_12h = weather_main

    # 3-day coarse summary (next 24*3 hours)
    next3 = []
    idx = 0
    for d in range(1, 4):
        slice_ = data.get("list", [])[idx:idx+8]  # 8 * 3h = 24h
        idx += 8
        rain_d = sum([x.get("rain", {}).get("3h", 0.0) for x in slice_])
        wind_d = max([x.get("wind", {}).get("speed", 0.0) for x in slice_] or [0.0])
        next3.append({"day": d, "rain_mm": round(rain_d, 1), "wind_ms": round(wind_d, 1)})

    return {
        "source": "openweather",
        "next_12h": {"rain_mm": round(rain_12h, 1), "wind_ms": round(max_wind_12h, 1), "conditions": condition_12h},
        "next_3d": next3
    }

# -------------------------------
# 3) Risk evaluation (simple rules)
# -------------------------------
def compute_risk(sensor, forecast):
    """
    Simple, explainable rule-based risk score that your AI can refine.
    """
    risk = 0
    reasons = []
    if forecast["next_12h"]["rain_mm"] >= 20:
        risk += 2; reasons.append("heavy rain expected in next 12h")
    if forecast["next_12h"]["wind_ms"] >= 12:
        risk += 2; reasons.append("strong winds expected in next 12h")
    if sensor["soil_moisture_pct"] >= 80:
        risk += 1; reasons.append("soil already wet (flood risk)")
    if sensor["wind_speed_ms"] >= 10:
        risk += 1; reasons.append("current high winds in field")
    return risk, reasons

# -------------------------------
# 4) OpenAI: local-language summary + actionable advice
# -------------------------------
def generate_farmer_advice(sensor, forecast, language_code="te"):
    """
    Uses Responses API to: (a) summarize, (b) advise actions, (c) keep it short.
    """
    # model choice: pick your latest text-capable model (e.g., gpt-4o-mini)
    model = "gpt-4o-mini"

    # Hint: provide tight, structured context for reproducible outputs
    sys_prompt = f"""You are an agriculture extension assistant for Indian farmers.
Write in ISO language code: {language_code}.
Village: {VILLAGE_NAME}, State: {STATE}.
Be concise (<= 120 words), bullet points. Include:
- Micro forecast (12h) from the data
- Actionable steps if heavy rain or wind expected
- Simple, friendly tone
"""

    user_payload = {
        "sensors": sensor,
        "forecast": forecast,
        "now_ist": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Data (JSON): {json.dumps(user_payload, ensure_ascii=False)}"}
        ],
    )
    # The Responses API returns content in .output_text for convenience
    return resp.output_text

# -------------------------------
# 5) OpenAI TTS → audio advisory (mp3)
# -------------------------------
def synthesize_tts(text, out_path="advice.mp3", voice="alloy"):
    """
    Uses Text-to-Speech endpoint to produce an MP3 farmers can hear on phones.
    """
    # See TTS guide. Voice names differ by account; 'alloy' is a safe default. :contentReference[oaicite:1]{index=1}
    audio_resp = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=voice,
        input=text,
        format="mp3"
    )
    with open(out_path, "wb") as f:
        f.write(audio_resp.read())
    return out_path

# -------------------------------
# 6) (Optional) WhatsApp/SMS alert
# -------------------------------
def send_alert(message_text, audio_path=None):
    if not twilio:
        print("[ALERT] Twilio not configured. Printing instead:\n", message_text)
        return

    if TO_WA and TW_FROM_WA:
        twilio.messages.create(from_=TW_FROM_WA, to=TO_WA, body=message_text)
        if audio_path:
            twilio.messages.create(from_=TW_FROM_WA, to=TO_WA, body="Audio advisory:",
                                   media_url=[f"https://file.io"])  # <- Host your mp3 and put URL here

    if TO_SMS and TW_FROM_SMS:
        twilio.messages.create(from_=TW_FROM_SMS, to=TO_SMS, body=message_text)

# -------------------------------
# 7) Auto photo capture on risk
# -------------------------------
def capture_photo(filename="field_capture.jpg", camera_index=0):
    cam = cv2.VideoCapture(camera_index)
    ok, frame = cam.read()
    if ok:
        cv2.imwrite(filename, frame)
    cam.release()
    return ok, filename

# -------------------------------
# 8) (Optional) Voice → text with Whisper (farmer asks a question)
# -------------------------------
def transcribe_farmer_audio(audio_file_path: str):
    """
    Upload a short voice note from the farmer and transcribe with Whisper.
    """
    # See Speech-to-Text docs & API ref. :contentReference[oaicite:2]{index=2}
    with open(audio_file_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )
    return transcript.text

# -------------------------------
# Main demo flow
# -------------------------------
def main():
    # 1) Read sensors
    sensors = read_iot_sensors()

    # 2) Get forecast (replace with IMD/NASA/OpenWeather)
    forecast = get_weather_forecast()

    # 3) Simple risk score
    risk, reasons = compute_risk(sensors, forecast)

    # 4) Ask OpenAI to summarize + advise in local language
    advice_text = generate_farmer_advice(sensors, forecast, language_code=LANGUAGE)

    # 5) TTS audio
    audio_file = synthesize_tts(advice_text, out_path="advice.mp3")

    # 6) Alert
    header = f"🌾 {VILLAGE_NAME} — Weather Advisory\n"
    risk_line = f"Risk Level: {risk} ({', '.join(reasons) if reasons else 'low'})\n"
    msg = header + risk_line + advice_text
    send_alert(msg, audio_path=audio_file)

    print("=== SENSOR DATA ===")
    print(json.dumps(sensors, indent=2))
    print("=== FORECAST ===")
    print(json.dumps(forecast, indent=2))
    print("=== ADVICE (", LANGUAGE, ") ===")
    print(advice_text)

    # 7) Auto capture a photo if risk high
    if CAPTURE_PHOTO_ON_RISK and risk >= 3:
        ok, photo = capture_photo()
        print(f"[PHOTO] Captured: {photo}" if ok else "[PHOTO] Failed to capture. Check webcam.")

if __name__ == "__main__":
    main()
