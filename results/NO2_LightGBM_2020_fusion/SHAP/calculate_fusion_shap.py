from pathlib import Path
import numpy as np,lightgbm as lgb,json,hashlib
o=Path('outputs/NO2_LightGBM_2020_fusion');out=o/'SHAP';out.mkdir(exist_ok=True)
d=np.load(o/'training_arrays.npz');X=d['X'];mask=d['valid']&(d['split']==2);test=np.flatnonzero(mask)
rng=np.random.default_rng(42);sample=np.sort(rng.choice(test,size=min(5000,len(test)),replace=False))
previous=np.load(o/'test_predictions.npz');y=previous['observed_no2_ppb'];pred=previous['predicted_no2_ppb']
special={'highest_observed':int(test[np.argmax(y)]),'largest_absolute_error':int(test[np.argmax(np.abs(pred-y))]),'median_observed':int(test[np.argsort(y)[len(y)//2]])}
indices=np.unique(np.concatenate([sample,np.array(list(special.values()))]))
b=lgb.Booster(model_file=str(o/'lightgbm_fusion_model.txt'))
print('Computing exact LightGBM TreeSHAP',len(indices),X.shape[1],flush=True)
values=b.predict(X[indices],pred_contrib=True,num_threads=4)
prediction=b.predict(X[indices],num_threads=4)
err=np.abs(values.sum(axis=1)-prediction);assert np.allclose(values.sum(axis=1),prediction,rtol=1e-10,atol=1e-8)
meta=json.loads((o/'data_metadata.json').read_text(encoding='utf-8'));assert len(meta['features'])+1==values.shape[1]
sampleflag=np.isin(indices,sample)
np.savez_compressed(out/'shap_values.npz',shap_values=values[:,:-1],base_values=values[:,-1],X=X[indices],prediction=prediction,observed=d['y'][indices],station_id=d['station_id'][indices],source_time_label=d['source_time_label'][indices],source_row_index=indices,random_sample=sampleflag)
report={'method':'LightGBM native pred_contrib=True TreeSHAP, tree-path-dependent training-cover reference; not interventional SHAP','model_sha256':hashlib.sha256((o/'lightgbm_fusion_model.txt').read_bytes()).hexdigest(),'lightgbm_version':lgb.__version__,'feature_names':meta['features'],'random_seed':42,'test_population':len(test),'uniform_random_sample':len(sample),'total_explained_rows':len(indices),'special_examples_original_row_indices':special,'global_importance_population':'uniform random sample only; extra examples excluded from rankings','maximum_additivity_error_ppb':float(err.max()),'base_value_min_ppb':float(values[:,-1].min()),'base_value_max_ppb':float(values[:,-1].max()),'notes':['Explains model output in ground NO2 ppb, not causal effects','Correlated predictors can share attribution; no independent ablation claim','Missing inputs handled by the fitted model, not imputed for SHAP','Sampled test explanations, not every test observation; no model retraining']}
(out/'metadata.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
