"""SettlementService에 대한 pytest 테스트 스위트."""

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from settlement.main import app
from settlement.models.models import Order, OrderStatus, SettlementStatus
from settlement.services.settlement_service import SettlementService


@pytest.fixture
def settlement_service():
    return SettlementService()


@pytest.fixture
def client():
    from settlement.main import svc as app_service

    app_service._orders.clear()
    app_service._settlements.clear()

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_orders(settlement_service):
    base_time = datetime(2026, 6, 15, 12, 0, 0)
    orders = [
        Order(
            order_id="ORD-001",
            merchant_id="M-001",
            customer_id="C-01",
            amount=Decimal("100000"),
            status=OrderStatus.COMPLETED,
            completed_at=base_time,
        ),
        Order(
            order_id="ORD-002",
            merchant_id="M-001",
            customer_id="C-02",
            amount=Decimal("50000"),
            status=OrderStatus.COMPLETED,
            completed_at=base_time + timedelta(days=1),
        ),
        Order(
            order_id="ORD-003",
            merchant_id="M-002",
            customer_id="C-03",
            amount=Decimal("30000"),
            status=OrderStatus.COMPLETED,
            completed_at=base_time,
        ),
    ]

    for order in orders:
        settlement_service.add_order(order)

    return orders


def test_calculate_settlement_empty_period_returns_zeroed_record(
    settlement_service,
    sample_orders,
):
    record = settlement_service.calculate_settlement(
        "M-001",
        datetime(2026, 7, 1, 0, 0, 0),
        datetime(2026, 7, 31, 23, 59, 59),
    )

    assert record.order_count == 0
    assert record.total_sales == Decimal("0")
    assert record.total_fee == Decimal("0")
    assert record.net_amount == Decimal("0")
    assert record.status == SettlementStatus.PENDING


def test_process_settlement_unknown_id_returns_none(settlement_service):
    result = settlement_service.process_settlement("STL-NONEXISTENT")

    assert result is None


def test_list_settlements_supports_merchant_and_status_filters(
    settlement_service,
    sample_orders,
):
    start = datetime(2026, 6, 1, 0, 0, 0)
    end = datetime(2026, 6, 30, 23, 59, 59)

    record_m1 = settlement_service.calculate_settlement("M-001", start, end)
    settlement_service.calculate_settlement("M-002", start, end)

    settlement_service.process_settlement(record_m1.settlement_id)

    filtered_results = settlement_service.list_settlements(
        merchant_id="M-001",
        status=SettlementStatus.COMPLETED,
    )

    assert len(filtered_results) == 1
    assert filtered_results[0].settlement_id == record_m1.settlement_id
    assert filtered_results[0].merchant_id == "M-001"
    assert filtered_results[0].status == SettlementStatus.COMPLETED

    no_results = settlement_service.list_settlements(
        merchant_id="M-002",
        status=SettlementStatus.COMPLETED,
    )
    assert len(no_results) == 0


def test_service_complete_and_get_orders_flow(settlement_service):
    order = Order(
        order_id="ORD-100",
        merchant_id="M-900",
        customer_id="C-100",
        amount=Decimal("20000"),
    )

    settlement_service.add_order(order)
    completed = settlement_service.complete_order(order.order_id)

    assert completed is not None
    assert completed.status == OrderStatus.COMPLETED
    assert len(settlement_service.get_orders()) == 1
    assert len(settlement_service.get_orders("M-900")) == 1


def test_api_health_and_order_flow(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    payload = {
        "order_id": "ORD-API-001",
        "merchant_id": "M-API",
        "customer_id": "C-API",
        "amount": "50000",
        "fee_rate": "0.03",
        "status": "pending",
    }
    create_response = client.post("/api/v1/orders", json=payload)
    assert create_response.status_code == 201
    assert create_response.json()["order_id"] == payload["order_id"]

    complete_response = client.put("/api/v1/orders/ORD-API-001/complete")
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == OrderStatus.COMPLETED.value

    list_response = client.get("/api/v1/orders?merchant_id=M-API")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_api_settlement_and_process_flow(client):
    payload = {
        "order_id": "ORD-API-002",
        "merchant_id": "M-API",
        "customer_id": "C-API",
        "amount": "75000",
        "fee_rate": "0.03",
        "status": "pending",
    }
    client.post("/api/v1/orders", json=payload)
    client.put("/api/v1/orders/ORD-API-002/complete")

    settlement_payload = {
        "merchant_id": "M-API",
        "period_start": "2026-06-01T00:00:00",
        "period_end": "2026-06-30T23:59:59",
    }
    create_settlement = client.post("/api/v1/settlements", json=settlement_payload)
    assert create_settlement.status_code == 201
    settlement_id = create_settlement.json()["settlement_id"]

    list_settlements = client.get("/api/v1/settlements?merchant_id=M-API&status=pending")
    assert list_settlements.status_code == 200
    assert len(list_settlements.json()) == 1

    process_response = client.post(f"/api/v1/settlements/{settlement_id}/process")
    assert process_response.status_code == 200
    assert process_response.json()["status"] == SettlementStatus.COMPLETED.value


def test_api_not_found_paths_return_404(client):
    missing_order = client.put("/api/v1/orders/NOPE/complete")
    assert missing_order.status_code == 404

    missing_settlement = client.post("/api/v1/settlements/NOPE/process")
    assert missing_settlement.status_code == 404
