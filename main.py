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


# === РАСЧЁТ RSI (Алгоритм Уайлдера) ===
def calculate_rsi(closes, period=14):
    try:
        if len(closes) < period + 1:
            return 50.0
        
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0.0 for d in deltas]
        losses = [-d if d < 0 else 0.0 for d in deltas]
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    except Exception as e:
        logger.error(f'Ошибка расчёта RSI: {e}')
        return 50.0


# === ПОЛУЧЕНИЕ ДАННЫХ С НЕСКОЛЬКИХ БИРЖ ===
def get_btc_data():
    """Пытается получить данные с нескольких бирж по очереди"""
    
    # Источник 1: MEXC API (работает в РФ)
    try:
        logger.info('Пробуем MEXC API...')
        url = "https://api.mexc.com/api/v3/klines"
        params = {
            'symbol': 'BTCUSDT',
            'interval': '4h',
            'limit': '100'
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        klines = response.json()
        
        closes = [float(k[4]) for k in klines]
        current_price = closes[-1]
        current_rsi = calculate_rsi(closes, period=14)
        
        logger.info(f'MEXC успешно: price={current_price}, rsi={current_rsi}')
        return current_price, current_rsi, 'MEXC'
    except Exception as e:
        logger.error(f'MEXC ошибка: {e}')
    
    # Источник 2: Gate.io API
    try:
        logger.info('Пробуем Gate.io API...')
        url = "https://api.gateio.ws/api/v4/spot/candlesticks"
        params = {
            'currency_pair': 'BTC_USDT',
            'interval': '4h',
            'limit': '100'
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        klines = response.json()
        
        # Gate.io возвращает в обратном порядке
        klines.reverse()
        closes = [float(k[2]) for k in klines]  # индекс 2 = close price
        current_price = closes[-1]
        current_rsi = calculate_rsi(closes, period=14)
        
        logger.info(f'Gate.io успешно: price={current_price}, rsi={current_rsi}')
        return current_price, current_rsi, 'Gate.io'
    except Exception as e:
        logger.error(f'Gate.io ошибка: {e}')
    
    # Источник 3: CoinGecko (только цена, RSI через альтернативный расчёт)
    try:
        logger.info('Пробуем CoinGecko API...')
        # Получаем текущую цену
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            'ids': 'bitcoin',
            'vs_currencies': 'usd'
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        current_price = float(data['bitcoin']['usd'])
        
        # Получаем исторические данные за последние 14 дней для RSI
        url2 = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        params2 = {
            'vs_currency': 'usd',
            'days': '14',
            'interval': 'daily'
        }
        response2 = requests.get(url2, params=params2, timeout=10)
        response2.raise_for_status()
        data2 = response2.json()
        
        # Извлекаем цены
        prices = [p[1] for p in data2['prices']]
        
        if len(prices) >= 15:
            current_rsi = calculate_rsi(prices, period=14)
        else:
            current_rsi = 50.0  # Нейтральное значение если данных мало
        
        logger.info(f'CoinGecko успешно: price={current_price}, rsi={current_rsi}')
        return current_price, current_rsi, 'CoinGecko'
    except Exception as e:
        logger.error(f'CoinGecko ошибка: {e}')
    
    # Все источники не сработали
    logger.error('Все биржи недоступны')
    return None, None, None


# === ОТПРАВКА В TELEGRAM ===
def send_telegram_message(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {
        'chat_id': CHAT_ID,
        'text': message
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        logger.info(f'Telegram response: {response.status_code}')
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f'Ошибка отправки: {e}')
        return False


# === АНАЛИЗ СИГНАЛА ===
def analyze_signal(rsi, price, signal_type, volume_ratio=1.0):
    try:
        signals = []
        score = 0

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

        if volume_ratio > 1.5:
            signals.append(f"Объем выше среднего в {volume_ratio:.1f}x")
            score += 1
        elif volume_ratio > 1.2:
            signals.append(f"Объем выше среднего ({volume_ratio:.1f}x)")
            score += 0.5
        else:
            signals.append(f"Объем средний ({volume_ratio:.1f}x)")

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
RSI (4H): {rsi:.2f}
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


# === LIVE CHECK ===
@app.route('/live-check', methods=['GET'])
def live_check():
    try:
        price, rsi, source = get_btc_data()
        
        if price is None or rsi is None:
            return jsonify({'status': 'error', 'message': 'Все биржи недоступны'}), 500
        
        # Минимальное сообщение для теста
        test_message = f"BTC Live Check\nЦена: ${price:,.0f}\nRSI: {rsi:.2f}\nИсточник: {source}"
        
        success = send_telegram_message(test_message)
        
        return jsonify({
            'status': 'success' if success else 'failed',
            'rsi': round(rsi, 2),
            'price': price,
            'source': source
        })
    except Exception as e:
        logger.error(f'Ошибка live-check: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500


# === DEBUG API ===
@app.route('/debug-api', methods=['GET'])
def debug_api():
    """Проверяет доступность всех бирж"""
    results = {}
    
    # MEXC
    try:
        r = requests.get('https://api.mexc.com/api/v3/ping', timeout=5)
        results['MEXC'] = 'OK' if r.status_code == 200 else f'Error {r.status_code}'
    except Exception as e:
        results['MEXC'] = f'Error: {str(e)[:50]}'
    
    # Gate.io
    try:
        r = requests.get('https://api.gateio.ws/api/v4/spot/currencies', timeout=5)
        results['Gate.io'] = 'OK' if r.status_code == 200 else f'Error {r.status_code}'
    except Exception as e:
        results['Gate.io'] = f'Error: {str(e)[:50]}'
    
    # CoinGecko
    try:
        r = requests.get('https://api.coingecko.com/api/v3/ping', timeout=5)
        results['CoinGecko'] = 'OK' if r.status_code == 200 else f'Error {r.status_code}'
    except Exception as e:
        results['CoinGecko'] = f'Error: {str(e)[:50]}'
    
    return jsonify(results)


# === WEBHOOK ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if data.get('secret') != WEBHOOK_SECRET:
            return jsonify({'status': 'error'}), 401

        message, score = analyze_signal(
            rsi=float(data.get('rsi', 100)),
            price=float(data.get('price', 0)),
            signal_type=data.get('signal_type', 'Webhook'),
            volume_ratio=float(data.get('volume_ratio', 1.0))
        )
        success = send_telegram_message(message)
        return jsonify({'status': 'success' if success else 'failed', 'score': score})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# === ТЕСТ ===
@app.route('/test', methods=['GET'])
def test():
    message, score = analyze_signal(rsi=28.5, price=81500, signal_type='Тест', volume_ratio=1.8)
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
