from pathlib import Path
import numpy as np,pandas as pd,json,shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
o=Path('outputs/NO2_LightGBM_2020_fusion/SHAP');d=np.load(o/'shap_values.npz');m=json.loads((o/'metadata.json').read_text(encoding='utf-8'));names=m['feature_names']
sv=d['shap_values'];X=d['X'];random=d['random_sample'];S=sv[random];V=X[random]
importance=np.abs(S).mean(axis=0);order=np.argsort(importance)[::-1]
rank=pd.DataFrame({'feature':names,'mean_abs_shap_ppb':importance,'mean_signed_shap_ppb':S.mean(axis=0),'missing_fraction_sample':np.isnan(V).mean(axis=0)}).sort_values('mean_abs_shap_ppb',ascending=False)
rank.to_csv(o/'global_shap_importance.csv',index=False)
ids=pd.DataFrame({'source_row_index':d['source_row_index'],'station_id':d['station_id'],'source_time_label_kst':d['source_time_label'],'observed_no2_ppb':d['observed'],'prediction_ppb':d['prediction'],'base_value_ppb':d['base_values'],'random_sample':random})
pd.concat([ids,pd.DataFrame(sv,columns=['shap_'+x for x in names])],axis=1).to_csv(o/'sample_shap_values.csv.gz',index=False,compression='gzip')
pd.concat([ids[['source_row_index','station_id','source_time_label_kst']],pd.DataFrame(X,columns=names)],axis=1).to_csv(o/'sample_feature_values.csv.gz',index=False,compression='gzip')
top=order[:20];plt.figure(figsize=(10,7));plt.barh(np.arange(len(top)),importance[top][::-1]);plt.yticks(np.arange(len(top)),[names[i] for i in top[::-1]]);plt.xlabel('Mean |SHAP value| (ground NO2 ppb)');plt.title('Test sample: global importance (n=5,000)');plt.tight_layout();plt.savefig(o/'shap_importance.png',dpi=170);plt.close()
fig,ax=plt.subplots(figsize=(11,8));rng=np.random.default_rng(42)
for row,col in enumerate(top[::-1]):
    s=S[:,col];v=V[:,col];finite=np.isfinite(v);edges=np.linspace(s.min()-1e-9,s.max()+1e-9,70);bins=np.clip(np.digitize(s,edges)-1,0,68);counts=np.bincount(bins,minlength=69);jitter=rng.uniform(-1,1,len(s))*.35*np.sqrt(counts[bins]/max(1,counts.max()))
    if finite.any():
        lo,hi=np.percentile(v[finite],[1,99]);color=np.clip((v[finite]-lo)/(hi-lo if hi>lo else 1),0,1)
        ax.scatter(s[finite],row+jitter[finite],c=color,cmap='coolwarm',vmin=0,vmax=1,s=5,alpha=.5,rasterized=True)
    ax.scatter(s[~finite],row+jitter[~finite],c='#888888',s=6,alpha=.5,rasterized=True)
ax.set_yticks(np.arange(len(top)),[names[i] for i in top[::-1]]);ax.axvline(0,color='#777777',lw=.8);ax.set_xlabel('SHAP value (ppb): negative lowers prediction, positive raises it');ax.set_title('TreeSHAP summary: top 20 features; gray = missing input')
fig.colorbar(plt.cm.ScalarMappable(norm=Normalize(0,1),cmap='coolwarm'),ax=ax,label='Feature value (low to high; scaled per feature)');fig.tight_layout();fig.savefig(o/'shap_summary.png',dpi=170);plt.close(fig)
groups={'Time':list(range(7)),'Coordinates':[7,8],'ERA5':[i for i,n in enumerate(names) if n.startswith('era5_')],'ASOS':[i for i,n in enumerate(names) if n.startswith('asos_')],'TROPOMI':[i for i,n in enumerate(names) if n.startswith('satellite_')]}
g=pd.DataFrame([{'group':k,'mean_abs_group_sum_shap_ppb':float(np.abs(S[:,ix].sum(axis=1)).mean()),'sum_mean_abs_individual_shap_ppb':float(importance[ix].sum())} for k,ix in groups.items()]).sort_values('mean_abs_group_sum_shap_ppb')
g.to_csv(o/'group_shap_importance.csv',index=False)
ax=g.set_index('group').mean_abs_group_sum_shap_ppb.plot.barh(figsize=(8,4));ax.set_xlabel('Mean |sum of SHAP within group| (ppb)');ax.set_title('Grouped attribution (within-group signs can cancel)');plt.tight_layout();plt.savefig(o/'shap_group_importance.png',dpi=170);plt.close()
fig,axes=plt.subplots(2,3,figsize=(13,8))
for ax,col in zip(axes.ravel(),order[:6]):
    keep=np.isfinite(V[:,col]);ax.scatter(V[keep,col],S[keep,col],s=5,alpha=.25);ax.axhline(0,color='gray',lw=.7);ax.set_xlabel(names[col],fontsize=8);ax.set_ylabel('SHAP (ppb)');ax.tick_params(labelsize=8)
fig.suptitle('Feature value versus SHAP attribution (missing values omitted)');fig.tight_layout();fig.savefig(o/'shap_dependence_top6.png',dpi=170);plt.close(fig)
examples=[]
for label,index in m['special_examples_original_row_indices'].items():
    r=int(np.flatnonzero(d['source_row_index']==index)[0]);ranked=np.argsort(np.abs(sv[r]))[::-1];selected=ranked[:10];vals=list(sv[r,selected])+[float(sv[r,ranked[10:]].sum())];labels=[names[i] for i in selected]+['All remaining features']
    fig,ax=plt.subplots(figsize=(11,6));current=float(d['base_values'][r]);low=current;high=current
    for j,(v,labelname) in enumerate(zip(vals,labels)):
        ax.barh(j,abs(v),left=min(current,current+v),color='#d9485f' if v>=0 else '#3182bd',height=.65);current+=v;low=min(low,current);high=max(high,current)
        ax.annotate(f'{v:+.2f}',(current,j),xytext=(4 if v>=0 else -4,0),textcoords='offset points',va='center',ha='left' if v>=0 else 'right',fontsize=8)
    ax.axvline(d['base_values'][r],color='gray',ls='--',lw=1);ax.scatter([d['prediction'][r]],[len(vals)],c='black',s=35,zorder=3);ax.set_yticks(range(len(vals)+1),labels+['Final prediction']);ax.invert_yaxis();pad=max(3,(high-low)*.15);ax.set_xlim(low-pad,high+pad);ax.set_xlabel('Ground NO2 model output (ppb)')
    title=f"{label}: station {d['station_id'][r]}, KST label {d['source_time_label'][r]}\nbase={d['base_values'][r]:.2f}; predicted={d['prediction'][r]:.2f}; observed={d['observed'][r]:.2f} ppb"
    ax.set_title(title,fontsize=10);fig.tight_layout();fname=f'local_{label}.png';fig.savefig(o/fname,dpi=160);plt.close(fig)
    examples.append({'example':label,'station_id':int(d['station_id'][r]),'source_time_label_kst':int(d['source_time_label'][r]),'observed_ppb':float(d['observed'][r]),'prediction_ppb':float(d['prediction'][r]),'base_value_ppb':float(d['base_values'][r]),'image':fname})
pd.DataFrame(examples).to_csv(o/'local_examples.csv',index=False)
rows=''.join(f"<tr><td>{i+1}</td><td>{x.feature}</td><td>{x.mean_abs_shap_ppb:.3f}</td></tr>" for i,x in enumerate(rank.head(10).itertuples()))
body=f'''<h1>지상 NO₂ 융합 모델 SHAP 분석</h1><p>2020년 11–12월 실측 평가 관측 {m['test_population']:,}개 중 균등 무작위 5,000개(seed=42)를 분석했습니다. 특수 사례 3종은 설명용으로 추가하며 전체 중요도 계산에는 추가 사례를 포함하지 않았습니다. 실제 계산 관측은 {m['total_explained_rows']:,}개입니다.</p><p>LightGBM 내장 TreeSHAP(pred_contrib=True), 학습 트리의 경로·커버를 기준으로 계산했습니다. 별도의 interventional 배경표본을 사용하지 않았습니다. 모델을 재학습하지 않았습니다.</p><p>기여도 단위는 지상 NO₂ ppb입니다. 기준값 + 각 변수 SHAP 합 = 예측값이며 최대 오차는 {m['maximum_additivity_error_ppb']:.2e} ppb로 검증했습니다. 기준값은 {m['base_value_min_ppb']:.3f} ppb입니다.</p><h2>전체 중요도 상위 10개</h2><table><tr><th>순위</th><th>변수</th><th>평균 절대 SHAP (ppb)</th></tr>{rows}</table><p>절대값은 예측 기여의 크기이며 양/음 방향을 뜻하지 않습니다. 아래 요약도에서 오른쪽은 예측 증가, 왼쪽은 감소입니다. 빨강은 해당 변수의 높은 값, 파랑은 낮은 값, 회색은 결측입니다.</p><h2>SHAP 중요도</h2><img src="shap_importance.png"><h2>기여도 분포</h2><img src="shap_summary.png"><h2>자료군별 기여</h2><img src="shap_group_importance.png"><p>자료군별 값은 관측마다 해당 군 SHAP를 더한 후 절대값 평균을 취했습니다. 개별 변수 평균 절대값 합과 다르며 같은 군 내 양/음 기여가 상쇄될 수 있습니다.</p><h2>주요 변수 값과 기여도</h2><img src="shap_dependence_top6.png"><p>연관성을 보여 주는 모델 설명이며 인과효과가 아닙니다. 시간 sin/cos, 기온/이슬점, 기압, 풍속 등 상관된 변수 사이에서 기여도가 나뉠 수 있습니다. 이 분석은 자료군을 제외해 재학습하는 ablation 실험이 아닙니다.</p>'''
for x in examples:body+=f'<h2>개별 예측: {x["example"]}</h2><img src="{x["image"]}">'
body+='<p>기존 좌표·시간 연결과 위성 노드/hour-bin 대용 연결의 한계는 그대로 적용됩니다. 이는 평가기간 표본의 설명이며 전체 기간·공간에 대한 중요도 순위를 보장하지 않습니다.</p>'
(o/'report.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><title>NO2 SHAP 분석</title><style>body{font-family:Arial,sans-serif;max-width:1100px;margin:32px auto;line-height:1.7}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:8px}img{max-width:100%}</style>'+body+'</html>',encoding='utf-8')
(o/'README.md').write_text('''# SHAP 분석 결과
LightGBM native TreeSHAP, 무작위 평가표본 5000개. 모델 재학습 없음.
report.html: 설명과 그래프. global_shap_importance.csv: 평균 절대기여도 순위.
group_shap_importance.csv: 자료군별 기여도. sample_shap_values.csv.gz: 기여도와 기준값/예측값. sample_feature_values.csv.gz: 해당 입력값.
shap_values.npz: 계산 배열. metadata.json: 모델 SHA256, 방법, 표본 추출, 합산 검증, 주의사항.
개별 사례 3개는 추가 설명용이며 중요도 순위는 무작위 5000개만 계산합니다.
기준값+SHAP 합=예측값 검증 완료. ppb 단위의 모델 설명으로 인과적 영향이 아닙니다.
''',encoding='utf-8')
for file in ['calculate_fusion_shap.py','report_fusion_shap.py']:shutil.copy2(Path('work')/file,o/file)
print(rank.head(10).to_string(index=False));print(g.to_string(index=False))
