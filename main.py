from flask import Flask, request, jsonify
import requests
import logging
from datetime import datetime
import os

app = Flask(__name__)

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '8933641686:AAEhw8S8ZN5cskGukui3RxL1VE7I3eszHsk')
CHAT_ID = int(os.environ.get('CHAT_ID', '172606168'))
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', 'QQQwww111!!!')

SUPPORT_LEVEL = 80113
RESISTANCE_LEVEL = 86620

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


# === ОТПРАВКА В TELEGRAM ===
def send_telegram_message(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {
        'chat_id': CHAT_ID,
        'text': message
        # Убрали parse_mode: 'HTML'
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        logger.info(f'Telegram response: {response.status_code} - {response.text}')
        if response.status_code != 200:
            logger.error(f'Telegram error: {response.status_code} - {response.text}')
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f'Ошибка отправки: {e}')
        return False


# === АНАЛИЗ СИГНАЛА ===
def analyze_signal(data):
    try:
        rsi = float(data.get('rsi', 100))
        price = float(data.get('price', 0))
        signal_type = data.get('signal_type', 'Неизвестно')
        volume_ratio = float(data.get('volume_ratio', 1.0))

        signals = []
        score = 0

        # RSI
        if rsi < 25:
            signals.append("RSI в глубокой перепроданности (< 25)")
            score += 1
        elif rsi < 30:
            signals.append("RSI в зоне перепроданности (< 30)")
            score += 1
        elif rsi < 40:
            signals.append("RSI приближается к перепроданности")
            score += 0.5
        else:
            signals.append("RSI не в зоне перепроданности")

        # Цена
        distance = ((price - SUPPORT_LEVEL) / SUPPORT_LEVEL) * 100
        if distance < 1:
            signals.append(f"Цена на поддержке ({distance:.2f}%)")
            score += 1
        elif distance < 3:
            signals.append(f"Цена близко к поддержке ({distance:.2f}%)")
            score += 1
        elif distance < 5:
            signals.append(f"Цена приближается к поддержке ({distance:.2f}%)")
            score += 0.5
        else:
            signals.append(f"Цена далеко от поддержки ({distance:.2f}%)")

        # Объем
        if volume_ratio > 1.5:
            signals.append(f"Объем выше среднего в {volume_ratio:.1f}x")
            score += 1
        elif volume_ratio > 1.2:
            signals.append(f"Объем выше среднего ({volume_ratio:.1f}x)")
            score += 0.5
        else:
            signals.append(f"Объем средний ({volume_ratio:.1f}x)")

        # Рекомендация
        confidence = (score / 3) * 100
        if score >= 2.5:
            rec = "СИЛЬНЫЙ СИГНАЛ К ПОКУПКЕ!"
            action = "Вход 70-80% капитала"
        elif score >= 1.5:
            rec = "УМЕРЕННЫЙ СИГНАЛ"
            action = "Вход 30-50% капитала"
        else:
            rec = "СЛАБЫЙ СИГНАЛ"
            action = "Ждать"

        stop_loss = price * 0.96
        risk_reward = (RESISTANCE_LEVEL - price) / (price - stop_loss) if price > stop_loss else 0

        message = f"""
BTC SIGNAL: {signal_type}

Анализ:
{chr(10).join(signals)}

Цена: ${price:,.0f}
RSI: {rsi:.2f}
Объем: {volume_ratio:.1f}x

Уровни:
- Поддержка: ${SUPPORT_LEVEL:,}
- Сопротивление: ${RESISTANCE_LEVEL:,}

Рекомендация: {rec}
{action}

Параметры:
- Стоп-лосс: ${stop_loss:,.0f} (-4%)
- Тейк-профит: ${RESISTANCE_LEVEL:,}
- Риск/Прибыль: 1:{risk_reward:.2f}
- Уверенность: {confidence:.0f}%

Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}
"""
        return message, score
    except Exception as e:
        return f"Ошибка: {e}", 0


# === WEBHOOK ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if data.get('secret') != WEBHOOK_SECRET:
            return jsonify({'status': 'error'}), 401

        message, score = analyze_signal(data)
        success = send_telegram_message(message)

        return jsonify({'status': 'success' if success else 'failed', 'score': score})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# === ТЕСТ ===
@app.route('/test', methods=['GET'])
def test():
    test_data = {
        'secret': WEBHOOK_SECRET,
        'signal_type': 'Тест',
        'rsi': 28.5,
        'price': 81500,
        'volume_ratio': 1.8
    }
    message, score = analyze_signal(test_data)
    success = send_telegram_message(message)
    return jsonify({'status': 'success' if success else 'failed', 'score': score})


# === СТАТУС ===
@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        'status': 'online',
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
