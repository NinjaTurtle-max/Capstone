# SHAP 분석 결과
LightGBM native TreeSHAP, 무작위 평가표본 5000개. 모델 재학습 없음.
report.html: 설명과 그래프. global_shap_importance.csv: 평균 절대기여도 순위.
group_shap_importance.csv: 자료군별 기여도. sample_shap_values.csv.gz: 기여도와 기준값/예측값. sample_feature_values.csv.gz: 해당 입력값.
shap_values.npz: 계산 배열. metadata.json: 모델 SHA256, 방법, 표본 추출, 합산 검증, 주의사항.
개별 사례 3개는 추가 설명용이며 중요도 순위는 무작위 5000개만 계산합니다.
기준값+SHAP 합=예측값 검증 완료. ppb 단위의 모델 설명으로 인과적 영향이 아닙니다.
