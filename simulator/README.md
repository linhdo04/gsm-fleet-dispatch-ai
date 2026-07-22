# Week 2 Simulator

Simulator tạo demand, trạng thái cung-cầu và lịch sử chấp nhận repositioning cho 30 zone/300 tài xế.

## Chạy nhanh một ngày

```powershell
python -m simulator.run --days 1 --start-date 2026-01-05 --output data/generated_smoke
python -m simulator.validate_outputs --output data/generated_smoke
```

## Sinh bộ dữ liệu 56 ngày

```powershell
python -m simulator.run --days 56 --start-date 2026-01-05 --output data/generated
python -m simulator.validate_outputs --output data/generated
python -m simulator.analyze_outputs --output data/generated
```

## Chạy kiểm thử

```powershell
python -m unittest discover -s simulator/tests -v
```

## Đầu ra

- `demand_events/day=YYYY-MM-DD.parquet`: request được sinh theo tick.
- `supply_snapshots/day=YYYY-MM-DD.parquet`: 30 snapshot zone cho mỗi tick 5 phút.
- `acceptance_history/day=YYYY-MM-DD.parquet`: feature và label cho Acceptance Model.
- `drivers_final.json`: trạng thái đội xe cuối run.
- `simulation_run.json`: metadata và tổng số event.
- `analysis/`: CSV, biểu đồ và sanity-check metrics.

Các file Parquet được partition theo ngày để chạy 56 ngày mà không giữ toàn bộ dữ liệu trong RAM.
