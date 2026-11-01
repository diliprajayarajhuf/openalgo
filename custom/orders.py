from .utils import calculate_position_size


def place_order(client, strategy, exchange, product, MAX_CAPITAL_TRADE, signals):
    placed_order = []
    if not isinstance(signals, list):
        signals = [signals]
    status = client.analyzerstatus()
    print(f"status {status}")
    if (status.get("status") != "success" or status.get("data", {}).get("analyze_mode") is not True):
        print("Analyzer Mode is OFF. Sandbox order will be placed.")
    for signal in signals:
        if signal['signal_type'].lower() == "buy" and 1==1: # Added for testing.
            quantity = calculate_position_size(signal['close'],MAX_CAPITAL_TRADE)
            response = client.placeorder(
                strategy=strategy,
                symbol=signal['symbol'],
                action="BUY",
                exchange=exchange,
                price_type="MARKET",
                product=product,
                quantity=quantity,
            )
            if response.get("status") == "success":
                placed_order.append(signal['symbol'])
            print("Buy Order Response:", response)
    return placed_order