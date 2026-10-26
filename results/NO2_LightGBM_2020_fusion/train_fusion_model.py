from pathlib import Path
import numpy as np
import lightgbm as lgb
import json,gzip,csv,sys
o=Path('outputs/NO2_LightGBM_2020_fusion');d=np.load(o/'training_arrays.npz')
X=d['X'];y=d['y'];split=d['split'];valid=d['valid'];ids=d['station_id'];coord=d['coordinate_available'];meta=json.loads((o/'data_metadata.json').read_text(encoding='utf-8'))
tr=valid&(split==0);va=valid&(split==1);te=valid&(split==2)
assert np.isfinite(y[valid]).all() and (y[valid]>=0).all()
params=dict(objective='regression',metric='rmse',learning_rate=.03,num_leaves=31,max_depth=8,min_data_in_leaf=100,feature_fraction=1.,lambda_l2=1.,seed=42,num_threads=4,verbosity=-1,deterministic=True,force_col_wise=True)
train=lgb.Dataset(X[tr],label=y[tr],feature_name=meta['features']);validation=lgb.Dataset(X[va],label=y[va],reference=train)
history={}
model=lgb.train(params,train,num_boost_round=1500,valid_sets=[validation],valid_names=['validation'],callbacks=[lgb.early_stopping(100),lgb.log_evaluation(100),lgb.record_evaluation(history)])
model.save_model(str(o/'lightgbm_fusion_model.txt'))
(o/'learning_curve.json').write_text(json.dumps(history),encoding='utf-8')
# One prediction pass for all actual labels, reused for subgroup metrics.
pred=np.full(len(y),np.nan);pred[valid]=model.predict(X[valid],num_threads=4)
def metrics(a,p):
 e=p-a;den=np.sum((a-a.mean())**2)
 return {'n':len(a),'rmse_ppb':float(np.sqrt(np.mean(e**2))),'mae_ppb':float(np.mean(np.abs(e))),'r2':float(1-np.sum(e**2)/den) if den else None,'bias_ppb':float(e.mean())}
seen=np.isin(ids,np.unique(ids[tr]));satcol=meta['features'].index('satellite_same_hour_available');recentcol=meta['features'].index('satellite_recent_24h_no2_mol_m2')
report={}
for name,mask in [('train',tr),('validation',va),('test',te),('test_with_coordinates',te&coord),('test_without_coordinates',te&~coord),('test_satellite_same_hour',te&(X[:,satcol]==1)),('test_without_satellite_same_hour',te&(X[:,satcol]!=1)),('test_recent_satellite_available',te&np.isfinite(X[:,recentcol])),('test_no_recent_satellite',te&~np.isfinite(X[:,recentcol])),('test_seen_stations',te&seen),('test_unseen_stations',te&~seen)]:
 if mask.any():report[name]=metrics(y[mask],pred[mask])
previous=np.load('outputs/NO2_LightGBM_2020_coordinates/test_predictions.npz')
assert np.array_equal(ids[te],previous['station_id']) and np.array_equal(d['source_time_label'][te],previous['source_time_label'])
assert np.array_equal(y[te],previous['observed_no2_ppb'])
coordinatepred=previous['predicted_no2_ppb'];timepred=previous['time_model_prediction_ppb']
report['comparison_same_test_rows']={'fusion':report['test'],'time_coordinates':metrics(y[te],coordinatepred),'time_only':metrics(y[te],timepred),'training_mean':metrics(y[te],np.full(te.sum(),y[tr].mean()))}
np.savez_compressed(o/'test_predictions.npz',station_id=ids[te],source_time_label=d['source_time_label'][te],observed_no2_ppb=y[te],predicted_no2_ppb=pred[te],coordinate_model_prediction_ppb=coordinatepred,time_model_prediction_ppb=timepred,coordinate_available=coord[te],satellite_same_hour_available=X[te,satcol],recent_satellite_available=np.isfinite(X[te,recentcol]))
with gzip.open(o/'test_predictions.csv.gz','wt',encoding='utf-8',newline='') as f:
 w=csv.writer(f);w.writerow(['station_id','source_time_label_kst','observed_no2_ppb','fusion_prediction_ppb','coordinate_model_prediction_ppb','time_model_prediction_ppb','coordinate_available','satellite_same_hour_available','recent_satellite_available']);w.writerows(zip(ids[te],d['source_time_label'][te],y[te],pred[te],coordinatepred,timepred,coord[te],X[te,satcol],np.isfinite(X[te,recentcol])))
importance=model.feature_importance(importance_type='gain')
with (o/'feature_importance.csv').open('w',encoding='utf-8',newline='') as f:
 w=csv.writer(f);w.writerow(['feature','gain']);w.writerows(zip(meta['features'],importance))
source_gain={key:float(sum(g for n,g in zip(meta['features'],importance) if n.startswith(prefix))) for key,prefix in [('ASOS','asos_'),('ERA5','era5_'),('TROPOMI','satellite_')]}
assert all(v>0 for v in source_gain.values()),'Every requested source must actually participate in model splits'
report.update(best_iteration=model.best_iteration,lightgbm_version=lgb.__version__,python=sys.executable,parameters=params,feature_count=X.shape[1],source_split_gain=source_gain,notes=['All ASOS/ERA5/TROPOMI sources included as inputs with missingness retained','Current-coordinate proxies used as authorized, no historical relocation validation','Satellite recent features use current/past hour-bin only, max24h; no future backfill','Same original labels/rows/temporal splits; no target imputation','Temporal evaluation only; unseen station subgroup is incidental, not designed spatial holdout'])
(o/'metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
# Saved model roundtrip on a deterministic distributed sample; full metrics checked independently in report script.
sample=np.flatnonzero(te)[::max(1,int(te.sum())//10000)]
saved=lgb.Booster(model_file=str(o/'lightgbm_fusion_model.txt'))
assert np.allclose(saved.predict(X[sample],num_threads=4),pred[sample],rtol=0,atol=1e-12)
v={'saved_model_prediction_match_sample_rows':len(sample),'same_evaluation_rows_targets_as_prior_models':True,'no_target_imputation':True,'requested_sources_used_in_model_splits':source_gain,'split_rows':{name:int(((split==i)&valid).sum()) for i,name in enumerate(['train','validation','test'])}}
(o/'verification.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'test':report['test'],'comparison':report['comparison_same_test_rows'],'best_iteration':model.best_iteration,'source_split_gain':source_gain},ensure_ascii=False,indent=2),flush=True)
