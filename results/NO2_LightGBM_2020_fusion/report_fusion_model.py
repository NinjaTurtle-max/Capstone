from pathlib import Path
import json,shutil,hashlib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
o=Path('outputs/NO2_LightGBM_2020_fusion')
m=json.loads((o/'metrics.json').read_text(encoding='utf-8'));meta=json.loads((o/'data_metadata.json').read_text(encoding='utf-8'))
d=np.load(o/'test_predictions.npz');df=pd.DataFrame({k:d[k] for k in d.files})
df['date']=pd.to_datetime(df.source_time_label.astype(str).str[:8],format='%Y%m%d')
series=['observed_no2_ppb','predicted_no2_ppb','coordinate_model_prediction_ppb']
labels=dict(zip(series,['Observed','ASOS + ERA5 + satellite fusion','Time + coordinates']))
ax=df.groupby('date')[series].mean().rename(columns=labels).plot(figsize=(10,4));ax.set_ylabel('Ground NO2 (ppb)');ax.set_xlabel('KST reporting date');plt.tight_layout();plt.savefig(o/'test_daily_comparison.png',dpi=160);plt.close()
ax=df.groupby(df.source_time_label%100)[series].mean().rename(columns=labels).plot(figsize=(9,4));ax.set_ylabel('Ground NO2 (ppb)');ax.set_xlabel('KST reporting hour (24 = midnight)');plt.tight_layout();plt.savefig(o/'test_hourly_comparison.png',dpi=160);plt.close()
plt.figure(figsize=(6,5));plt.hexbin(df.observed_no2_ppb,df.predicted_no2_ppb,gridsize=70,mincnt=1,bins='log');plt.colorbar(label='log10 count');mx=max(float(df.observed_no2_ppb.max()),float(df.predicted_no2_ppb.max()));plt.plot([0,mx],[0,mx],'k--',lw=1);plt.xlabel('Observed ground NO2 (ppb)');plt.ylabel('Fusion prediction (ppb)');plt.tight_layout();plt.savefig(o/'test_observed_predicted.png',dpi=160);plt.close()
imp=pd.read_csv(o/'feature_importance.csv').sort_values('gain');ax=imp.tail(20).set_index('feature').gain.plot.barh(figsize=(10,7));ax.set_xlabel('Split gain (not causal contribution)');plt.tight_layout();plt.savefig(o/'feature_importance_top20.png',dpi=160);plt.close()
curve=json.loads((o/'learning_curve.json').read_text());plt.figure(figsize=(8,4));plt.plot(np.arange(1,len(curve['validation']['rmse'])+1),curve['validation']['rmse']);plt.axvline(m['best_iteration'],color='gray',ls='--');plt.ylabel('Validation RMSE (ppb)');plt.xlabel('Boosting round');plt.tight_layout();plt.savefig(o/'validation_curve.png',dpi=160);plt.close()
df['error']=df.predicted_no2_ppb-df.observed_no2_ppb
def metric(g):
 e=g.error.to_numpy();y=g.observed_no2_ppb.to_numpy();den=np.sum((y-y.mean())**2)
 return dict(n=len(g),rmse_ppb=np.sqrt(np.mean(e**2)),mae_ppb=np.mean(np.abs(e)),bias_ppb=e.mean(),r2=1-np.sum(e**2)/den if den else np.nan)
pd.DataFrame([dict(station_id=k,**metric(g)) for k,g in df.groupby('station_id')]).to_csv(o/'test_station_metrics.csv',index=False)
pd.DataFrame([dict(month=k,**metric(g)) for k,g in df.groupby(df.source_time_label//10000%100)]).to_csv(o/'test_monthly_metrics.csv',index=False)
assert len(df)==m['test']['n'] and np.isclose(metric(df)['rmse_ppb'],m['test']['rmse_ppb'])
# Compare unchanged labels, split and first nine inputs in chunks to avoid excessive memory.
a=np.load(o/'training_arrays.npz');b=np.load('outputs/NO2_LightGBM_2020_coordinates/training_arrays.npz')
for k in ['y','split','valid','station_id','source_time_label']:assert np.array_equal(a[k],b[k],equal_nan=True)
xx=a['X'];bb=b['X'];assert np.array_equal(xx[:,:9],bb,equal_nan=True)
assert not np.isinf(xx).any()
assert a['source_time_label'][a['split']==0].max()<a['source_time_label'][a['split']==1].min()
assert a['source_time_label'][a['split']==1].max()<a['source_time_label'][a['split']==2].min()
age=xx[:,meta['features'].index('satellite_recent_age_hours')];assert np.all((age[np.isfinite(age)]>=0)&(age[np.isfinite(age)]<=24))
v=json.loads((o/'verification.json').read_text());v.update(independent_test_RMSE='passed',unchanged_targets_rows_splits_and_previous_inputs=True,finite_or_nan_features=True,recent_satellite_age_bounds_0_to24=True,chronological_split_boundaries=True)
(o/'verification.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
meta['ASOS_processed_sources']=[{'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(Path('outputs/ASOS_2020_processed/parquet').glob('*.parquet'))]
(o/'data_metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
for p in ['station_coordinate_linkage.csv','provided_station_coordinates.csv']:shutil.copy2(Path('outputs/NO2_LightGBM_2020_coordinates')/p,o/p)
shutil.copy2('outputs/ASOS_2020_processed/station_metadata_reference.csv',o/'asos_reference_metadata.csv')
for p in ['prepare_fusion_model.py','train_fusion_model.py','report_fusion_model.py']:shutil.copy2(Path('work')/p,o/p)
comp=m['comparison_same_test_rows'];test=m['test'];coord=comp['time_coordinates'];gain=(1-test['rmse_ppb']/coord['rmse_ppb'])*100
table='<table><tr><th>모델</th><th>RMSE ppb</th><th>MAE ppb</th><th>R²</th><th>편향 ppb</th></tr>'
for key,label in [('time_only','시간'),('time_coordinates','시간 + 좌표'),('fusion','시간 + 좌표 + ASOS + ERA5 + 위성')]:
 q=comp[key];table+=f"<tr><td>{label}</td><td>{q['rmse_ppb']:.3f}</td><td>{q['mae_ppb']:.3f}</td><td>{q['r2']:.3f}</td><td>{q['bias_ppb']:.3f}</td></tr>"
table+='</table>'
coverage=pd.read_csv(o/'feature_coverage.csv')
text=f'''# 2020년 지상 NO₂ LightGBM 융합 모델

학습 완료. 도시대기 474개 지점, 전체 {meta['master_rows']:,}행 보존. 결측 정답 {meta['missing_targets']:,}행은 보간하지 않고 학습/평가 제외.
1–8월 학습, 9–10월 검증, 11–12월 평가. 최대 1500회 중 검증 RMSE가 가장 낮은 반복을 선택했습니다(100회 조기종료 조건은 상한 도달 전 충족되지 않음). 실제 지상 NO₂ ppm×1000=ppb 정답. 변수 {m['feature_count']}개, 선택 트리 {m['best_iteration']}개.

## 포함 자료와 연결 방식
- 시간 7개 + 현재 좌표 2개: 제공 좌표 그대로 사용, 과거 이력 검증 없음. 452개 지점 연결, 22개 좌표 결측 유지.
- ERA5 8개: z850, thk, u_pbl, v_pbl, blh, sp, t2m 및 u_pbl/v_pbl 합성 풍속. 각 그룹 위도 정렬 방향을 개별 처리한 bilinear interpolation, 월별 시간 origin을 해석하여 UTC 연결. NetCDF 변수 단위 속성이 없어 수치를 원단위 그대로 입력, u_pbl/v_pbl을 10m 바람으로 부르지 않음. z850_anom은 상류 기준값 산출 정의 미상으로 제외.
- ASOS 13개: 풍속/u/v, 기온, 이슬점, 습도, 현지/해면기압, 보고 강수량과 집계 구간, 일사량, 관측 행 유무, 거리. 좌표가 있는 2020 지점 중 가장 가까운 한 지점, UTC 시간 일치. 거리 중앙값 {meta['ASOS_distance_summary_km']['median']:.2f}km, 최대 {meta['ASOS_distance_summary_km']['max']:.2f}km. 원본 QC와 결측 처리 결과를 유지. 겨울 RN은 3시간값이며 1시간값/무강수로 대체하지 않음.
- 위성 8개: 같은 hour-bin의 NO₂ 컬럼/QA/가중치 지원량/관측 유무/저품질 마스크 및 과거 24h 최근 컬럼/QA/경과시간. 원본 고품질 그룹을 원 가중치로 0.25° 노드에 집계하고 지점 주변 노드의 유효값을 정규화해 보간. 음수 위성 컬럼도 원 고품질 값으로 보존. mol/m²를 지상 ppb로 임의 변환하지 않음. 저품질 그룹은 농도값 없이 마스크만 존재하므로 농도로 사용하지 않음.

## 결측 및 시간
feature NaN 유지, 평균/선형 대체 없음. satellite recent는 과거/current hour-bin 값만 24h 이내 사용, 미래값 backfill 없음. 같은 시각 위성값이 없을 때도 행 유지. 위성 최근값은 지상 타깃 보간이 아님.
AirKorea KST 원표기의 24시를 다음날 00시로 정규화하여 -9h UTC. 시간평균 시작/종료 정의를 추가 검증하거나 임의 이동하지 않은 label-time proxy 연결. 정확한 관측 구간 검증이 완료된 정합으로 해석하면 안 됨.
UTC2019에 해당하는 연초 {meta['UTC_outside_2020_rows']:,}행은 외부 2020 자료 범위 밖이라 외부 feature NaN으로 유지. 지상 원자료와 기존 모델 평가 행은 모두 보존.

## 동일 평가 관측 {test['n']:,}개 비교
융합 RMSE {test['rmse_ppb']:.3f} ppb / MAE {test['mae_ppb']:.3f} ppb / R² {test['r2']:.3f}.
시간+좌표 모델 대비 RMSE {gain:.2f}% 변화(양수=개선).
모든 요청 자료군의 변수에 실제 모델 분할 이득이 있는지 검증했습니다. 중요도는 인과적 기여를 의미하지 않으며, 각 자료의 추가 효과를 분리한 ablation 실험은 수행하지 않았습니다.

## 해석 범위
제공 위성 자료에 원래 화소 좌표·정확한 overpass 시각이 없어 노드/hour-bin 대용 연결입니다. AirKorea/ASOS 현재 좌표의 역사적 정확성도 미검증입니다.
단일 연도의 계절을 포함한 시간 분리 평가이며, 공간 독립 holdout은 수행하지 않았습니다. 신설 지점 하위집단 지표는 설계된 공간 검증이 아닙니다. 본 모델은 동시간 기상과 위성으로 재구성하는 모델이며 미래예보 모델이 아닙니다.

## 결과 파일
report.html, lightgbm_fusion_model.txt, metrics.json, test_predictions.csv.gz, test_station_metrics.csv, test_monthly_metrics.csv, feature_coverage.csv, feature_importance.csv, verification.json.
전체 결합표 urban_no2_2020_fusion_master.parquet, 재학습 배열 training_arrays.npz. 원자료 및 연결 기준/SHA256은 data_metadata.json. 스크립트는 원 작업폴더 기준 상대 경로입니다.
'''
(o/'README.md').write_text(text,encoding='utf-8')
body=f'''<h1>2020년 지상 NO₂ LightGBM 융합 모델</h1><p>ASOS·ERA5·TROPOMI 모두 포함한 입력 {m['feature_count']}개, 선택 트리 {m['best_iteration']}개. 도시대기 실측 ppb 정답. 1–8월 학습 / 9–10월 검증 / 11–12월 평가.</p><h2>동일 평가 관측 {test['n']:,}개 비교</h2>{table}<p>시간+좌표 모델 대비 RMSE {gain:.2f}% 개선. 모든 요청 자료군이 실제 모델 분할에 사용됐는지 확인했습니다.</p><h2>연결·결측 처리</h2><p>ERA5는 위치 bilinear 보간, ASOS는 최근접 지점 연결, 위성은 제공 노드·가중치로 집계한 값의 공간 보간입니다. 위성은 같은 hour-bin 및 과거 24h 최근값을 제공하며 미래값 backfill은 하지 않았습니다. 지상 정답은 보간하지 않았고 feature 결측은 NaN으로 유지했습니다.</p><p>현재 좌표는 요청대로 과거 이력 검증 없이 사용했습니다. 위성 원 화소 좌표·정확한 시각은 제공되지 않아 노드/hour-bin 대용 연결입니다. AirKorea 시간평균 구간은 독립 검증하지 않은 표기시각 기준입니다. ERA5 u_pbl/v_pbl은 10m 바람으로 해석하지 않습니다. 정확한 세부 처리 기준은 README.md와 data_metadata.json에 기록했습니다.</p><h2>일평균 비교</h2><img src="test_daily_comparison.png"><h2>시각별 비교</h2><img src="test_hourly_comparison.png"><h2>실측–예측 분포</h2><img src="test_observed_predicted.png"><h2>주요 변수</h2><img src="feature_importance_top20.png"><h2>검증 학습 곡선</h2><img src="validation_curve.png"><p>계절 영향이 섞인 단일 연도 시간 분리 평가입니다. 설계된 공간 독립 검증은 수행하지 않았으며 최종 공간 일반화 성능을 의미하지 않습니다. 중요도는 인과적 영향이나 자료군의 독립 추가 효과를 뜻하지 않습니다.</p>'''
(o/'report.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><title>NO2 융합 모델 학습 결과</title><style>body{font-family:Arial,sans-serif;max-width:1050px;margin:32px auto;line-height:1.7}table{border-collapse:collapse}th,td{padding:10px;border:1px solid #ddd}img{max-width:100%}</style>'+body+'</html>',encoding='utf-8')
print(json.dumps({'test':test,'comparison':comp,'RMSE_improvement_vs_coordinate_pct':gain,'best_iteration':m['best_iteration']},ensure_ascii=False,indent=2))
