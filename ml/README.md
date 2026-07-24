# Week 3-4 — Forecast, Repositioning, Cost Model, Matching Engine, A/B testing

Train cac model tren du lieu simulator (Tuan 2) va chay thu Repositioning
Suggester + Matching Engine + A/B test tren simulator. Can chay simulator sinh
du lieu (`data/generated/`) truoc.

## Cai dependency

```powershell
pip install -r requirements-ml.txt
```

> `xgboost`/`lightgbm` chua duoc dung trong moi truong nay. Dung
> thay the tuong duong trong scikit-learn: `HistGradientBoostingRegressor` (cung ho
> Gradient Boosting nhu XGBoost) cho Forecast, `LogisticRegression` cho Acceptance —
> ca hai deu la lua chon duoc liet ke trong `report.md`.

## MLflow tracking

Ba lenh train Forecast, Acceptance va Cost tu dong tao experiment, log params,
metrics, artifacts, model signature/input example va dang ky model vao MLflow.
Tracking URI mac dinh la `http://127.0.0.1:5000` (tranh xung dot AirPlay tren
macOS). De dung server khac:

```powershell
$env:MLFLOW_TRACKING_URI = "http://mlflow.example:5000"
python -m ml.forecast_model --output ml/artifacts
```

Registered models:

- `fleet-dispatch-forecast-model`
- `fleet-dispatch-acceptance-model`
- `fleet-dispatch-cost-model`

## Chay tung buoc

```powershell
python -m ml.forecast_model --output ml/artifacts
python -m ml.acceptance_model --output ml/artifacts
python -m ml.repositioning_suggester --output ml/artifacts
python -m ml.repositioning_mcf --output ml/artifacts  # so sanh voi Minimum Cost Flow (OR-Tools)
python -m ml.cost_model --output ml/artifacts
python -m ml.matching_engine --output ml/artifacts   # SUPERSEDED, giu de tham khao
python -m ml.matching_flow --output ml/artifacts     # Matching Engine hien hanh (cascade)
python -m ml.ab_testing --days 7 --output data/ab_test              # 1 seed, nhanh
python -m ml.ab_testing --multi-seed --days 7 --output data/ab_test_multiseed  # 10 seed, ~9 phut
python -m ml.export_demo_data                                        # xuat data that cho frontend Tuan 5
```

## Chay toan bo end-to-end

```powershell
python -m ml.train_all --output ml/artifacts     # Week 3: Forecast + Acceptance + Suggester
python -m ml.train_week4 --output ml/artifacts   # Week 4: Cost Model + Matching Engine demo
```

## Dau ra (`ml/artifacts/`)

- `forecast_model.joblib`, `forecast_metrics.json`, `forecast_vs_actual.png`
- `acceptance_model.joblib`, `acceptance_metrics.json`
- `repositioning_suggester_summary.json`, `herding_comparison.csv`
- `week3_run_summary.json`: tong hop metrics ca 3 module
- `repositioning_comparison.json`, `greedy_suggestions.csv`, `mcf_distance_suggestions.csv`,
  `mcf_hybrid_suggestions.csv`: ket qua so sanh greedy vs MCF thuan khoang cach vs
  MCF 2 tang (hybrid) — xem phan tich day du trong `docs/repositioning_mcf_vs_greedy.md`
- `cost_model.joblib`, `cost_model_metrics.json`: Cost Prediction Model
- `matching_engine_summary.json`, `matching_hungarian_demo.csv`, `matching_pooling_demo.csv`
- `data/ab_test_multiseed/ab_test_summary_multi_seed.csv`: KPI 3 kich ban A/B, trung
  binh 10 seed — xem phan tich day du trong `docs/week4_matching_ab_test.md`

## Module

- `common.py`: load config/zones/parquet, feature thoi gian (gio, thu, holiday),
  lookup thoi tiet theo (ngay, gio) tu `demand_events`, chia tap chronological
  42/7/7 ngay theo `simulation_config.json`.
- `forecast_model.py`: target = `actual_demand` trong `supply_snapshots` (dung
  chinh la request_count_per_zone_per_5_minutes da tinh san boi simulator).
- `acceptance_model.py`: target = `accepted` trong `acceptance_history`; cot
  `p_accept_ground_truth` chi dung de so sanh AUC oracle, khong dua vao feature.
- `repositioning_suggester.py`: xep hang tai xe idle theo `p_accept` du doan tu
  model (thay vi chi khoang cach), co soft-reserve — dung lai khi deficit da duoc
  giai quyet. `simulate_herding_comparison()` minh hoa bang so vi sao co bat toggle
  chong herding lai giam duoc so gop y du thua qua nhieu tick.
- `repositioning_mcf.py`: 3 phuong an so sanh voi greedy —
  (1) MCF thuan khoang cach (coi zone thua/thieu la nguon/dich, chi phi = khoang
  cach), (2) MCF 2 tang "hybrid": layer 1 dung chi phi + demand da hieu chinh theo
  p_accept (co "soft demand" bang arc phat de tranh ep MCF di qua xa chi de lap du
  chi tieu), layer 2 van dung Acceptance Model de chon tai xe cu the. Ket luan: MCF
  thuan mu voi p_accept (quang duong thap nhung ty le chap nhan thap); hybrid can
  bang duoc ty le bu dap (~98%) nhung phai bo han 4/17 zone kho de doi lay ket qua
  do — khong phai chien thang ro rang, xem phan tich day du va bai hoc rut ra tu
  qua trinh thu-sai trong `docs/repositioning_mcf_vs_greedy.md`.
- `cost_model.py`: sinh dataset trip gia lap (khong dung OpenRouteService that,
  chua co API key) voi hieu ung phi tuyen tinh gio cao diem x thoi tiet, train
  `HistGradientBoostingRegressor` du doan `duration_minutes`. MAE 4.6 phut, tot hon
  han baseline tuyen tinh thuan (9.5 phut).
- `matching_engine.py`: **SUPERSEDED**, giu lai de tham khao — 2 che do (Hungarian
  Algorithm cho ghep 1-1 mac dinh, insertion heuristic cho ride-pooling khi
  mua/gio cao diem). Sau khi co `docs/business_design.md` chi tiet hon, quyet dinh
  la thay han bang `matching_flow.py` — khong dung Hungarian, khong con "che do
  toan cuc" bat/tat theo dieu kien nua. Xem `matching_flow.py`.
- `matching_flow.py`: **Matching Engine hien hanh**, dung `docs/business_design.md`
  ("Dac ta luong Matching & Repositioning") — Luong A `handle_new_request()`
  (cascade 4 buoc: gan truc tiep -> chen ghep chuyen -> cho incoming -> kich hoat
  repositioning) va Luong B `handle_idle_driver()` (pin -> deficit tai cho -> zone
  lan can -> soft-reserve), dung chung `find_and_reserve_driver_for_zone()` cho ca
  2 luong nhu spec yeu cau. `RouteEstimator` la `get_route()` thay the (chua co
  Google Routes API key nen luon fallback Haversine + Cost Prediction Model),
  co cache theo cap zone (`warm_cache()`) — cung mot loi hieu nang nhu
  `matching_engine.py` truoc do (goi `model.predict()` tung dong trong vong lap
  long nhau) gap lai o day va da sua bang cung 1 cach (cache batch truoc).
  Chay demo: `python -m ml.matching_flow --output ml/artifacts` ->
  `matching_flow_summary.json`. Unit test 3 ca bien theo dung yeu cau muc 5 cua
  spec (tranh chap driver, soft-reserve het han, deficit ve 0 giua batch),
  cong them test cho tram sac: `python -m unittest discover -s ml/tests`.
  Nhanh pin thap/nguy cap gio tra ve ca `nearest_station` (tram sac gan nhat
  that, qua `routing_client.py` + `data/charging_stations.json`), khong con
  chi tra ve action suong nhu truoc.
- `routing_client.py`: `GoogleRoutesClient` — `get_route()` that theo muc 2.8
  `business_design.md`, cache theo cap toa do (lam tron 4 chu so thap phan)
  vao file JSON tren dia, doc bien moi truong `GOOGLE_ROUTES_API_KEY`. Khong
  co key trong moi truong nay nen moi lan chay deu di qua nhanh fallback
  Haversine x 1.3 (co danh dau `is_fallback: true` ro rang, khong am tham
  gia mao la du lieu that) — da kiem chung ca 2 nhanh (co key gia lap bi loi
  mang/response sai dinh dang, va khong co key) bang
  `ml/tests/test_routing_client.py`. Dat bien moi truong do la dung ngay,
  khong can sua code goi module nay o dau khac.
- `data/generate_charging_stations.py` (o thu muc `data/`, khong phai `ml/`):
  sinh `data/charging_stations.json` — 8 tram phu deu 30 zone bang
  farthest-point sampling (khong dat ngau nhien/tuy tien), vi chua co du
  lieu tram sac that cua GSM.
- `ab_testing.py`: noi Repositioning Suggester vao vong lap chinh cua simulator
  (them method `_reposition_drivers` + status `incoming` vao `simulator/engine.py`,
  khong doi hanh vi mac dinh `A_PASSIVE` — da xac nhan lai output 56 ngay Tuan 2 y
  het truoc khi sua) de chay that ca 3 kich ban A/B tren simulator nhu report.md yeu
  cau, khong chi demo tren 1 snapshot. Chay 10 seed de tranh ket luan sai do nhieu
  ngau nhien. Xem ket qua va nhan dinh trong `docs/week4_matching_ab_test.md`.
- `export_demo_data.py`: xuat 4 file `scenario_{normal,rain,peak,holiday}.json` +
  `kpi_real.json` vao `frontend/public/data/` de frontend (Tuan 5) hien thi **du
  lieu that** thay cho `src/mock/scenario.ts`. Moi scenario chon 1 tick that tu
  `supply_snapshots` (56 ngay Tuan 2) dung dieu kien that (mua/gio cao diem/le), uu
  tien tick co deficit cao de demo ro; goi thang Repositioning Suggester + Acceptance
  Model that tren deficit that do, va `matching_flow.handle_new_request()` (khong
  con `matching_engine.hungarian_match`/`insertion_pooling_match` nua) cho tung
  request mot trong batch gia lap — payload `matching` gio la `action_breakdown`
  (dem so request roi vao moi 1 trong 4 hanh dong cua cascade) thay vi 1 field
  `mode` chung ca batch. Xac nhan bang Playwright: build production sach, chay
  dev server that, chup man hinh, kiem tra console khong loi (phat hien va sua 1
  bug key trung khi lam viec nay: nhieu goi y cung zone bi trung `suggestion_id`;
  va 1 bug CSS bang KPI bi tran ngoai panel).
