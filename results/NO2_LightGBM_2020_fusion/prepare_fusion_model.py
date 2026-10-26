from pathlib import Path
import json,zipfile,hashlib
import numpy as np
import pandas as pd
import netCDF4

ROOT=Path(r'C:\Users\wonhe\OneDrive\Desktop\딥러닝')
BASE=Path('outputs/NO2_LightGBM_2020_coordinates')
OUT=Path('outputs/NO2_LightGBM_2020_fusion');OUT.mkdir(parents=True,exist_ok=True)
master=pd.read_parquet(BASE/'urban_no2_2020_with_coordinates.parquet')
old=np.load(BASE/'training_arrays.npz');meta=json.loads((BASE/'data_metadata.json').read_text(encoding='utf-8'))
link=pd.read_csv(BASE/'station_coordinate_linkage.csv').set_index('station_code')
stations=np.unique(old['station_id']);S=len(stations);T=8784
lat=link.reindex(stations).latitude.to_numpy();lon=link.reindex(stations).longitude.to_numpy()
known=np.isfinite(lat)&np.isfinite(lon);ki=np.flatnonzero(known)
hours=((master.time_utc_label-pd.Timestamp('2020-01-01'))/pd.Timedelta(hours=1)).to_numpy(dtype=int)
station_index=np.searchsorted(stations,old['station_id']);in_year=(hours>=0)&(hours<T)
features=[];names=list(meta['features']);coverage={};units={};sources=[]
def append(name,values,unit):
    a=np.full(len(master),np.nan,dtype='float32')
    a[in_year]=values[hours[in_year],station_index[in_year]]
    features.append(a);names.append(name);units[name]=unit
    coverage[name]={'nonmissing_rows':int(np.isfinite(a).sum()),'nonmissing_fraction':float(np.isfinite(a).mean())}
def bilinear(g,var):
    ys=np.asarray(g['lat'][:]);xs=np.asarray(g['lon'][:]);arr=np.ma.filled(g[var][:],np.nan).astype('float32')
    if ys[0]>ys[-1]:ys=ys[::-1];arr=arr[:,::-1,:]
    if xs[0]>xs[-1]:xs=xs[::-1];arr=arr[:,:,::-1]
    yi=np.clip(np.searchsorted(ys,lat[ki],side='right')-1,0,len(ys)-2)
    xi=np.clip(np.searchsorted(xs,lon[ki],side='right')-1,0,len(xs)-2)
    fy=(lat[ki]-ys[yi])/(ys[yi+1]-ys[yi]);fx=(lon[ki]-xs[xi])/(xs[xi+1]-xs[xi])
    assert (fy>=0).all() and (fy<=1).all() and (fx>=0).all() and (fx<=1).all()
    result=np.zeros((arr.shape[0],len(ki)),dtype='float32')
    for yoff,xoff,w in [(0,0,(1-fy)*(1-fx)),(0,1,(1-fy)*fx),(1,0,fy*(1-fx)),(1,1,fy*fx)]:
        v=arr[:,yi+yoff,xi+xoff]
        result+=np.where(w[None,:]>0,v*w[None,:],0).astype('float32')
    return result

# ERA5: respect each group's independent latitude order, decode each monthly time origin.
era_vars={'era5_syn':['z850','thk'],'era5_wind':['u_pbl','v_pbl','blh','sp','t2m']}
era={v:np.full((T,S),np.nan,dtype='float32') for vs in era_vars.values() for v in vs}
with zipfile.ZipFile(ROOT/'era5_korean_peninsula_2020.zip') as z:
    files=sorted(n for n in z.namelist() if '/netcdf/' in n and n.endswith('.nc') and not n.startswith('__'))
    assert len(files)==12
    for file in files:
        nc=netCDF4.Dataset('memory',memory=z.read(file))
        for gn,vs in era_vars.items():
            g=nc.groups[gn];t=g['time'];decoded=netCDF4.num2date(t[:],t.units,calendar=getattr(t,'calendar','standard'))
            ht=((pd.to_datetime([str(x) for x in decoded])-pd.Timestamp('2020-01-01'))/pd.Timedelta(hours=1)).to_numpy(dtype=int)
            assert np.all(np.diff(ht)==1) and ht.min()>=0 and ht.max()<T
            for v in vs:era[v][np.ix_(ht,ki)]=bilinear(g,v)
        nc.close();print('ERA5',file,flush=True)
for v,a in era.items():append('era5_'+v+'_native',a,'source-native (monthly NetCDF has no variable unit attribute)')
append('era5_pbl_wind_speed_native',np.hypot(era['u_pbl'],era['v_pbl']),'same native velocity units as u_pbl/v_pbl; not 10m wind')
del era

# ASOS: one nearest station based on provided/reference current coordinates; never fill from a distant station at a later time.
asosmeta=pd.read_csv('outputs/ASOS_2020_processed/station_metadata_reference.csv')
asosids=pd.read_parquet('outputs/ASOS_2020_processed/parquet/asos_202001.parquet',columns=['station_id']).station_id.unique()
asosmeta=asosmeta[asosmeta.station_id.isin(asosids)&asosmeta.latitude.notna()&asosmeta.longitude.notna()].sort_values('station_id')
alat=np.deg2rad(asosmeta.latitude.to_numpy());alon=np.deg2rad(asosmeta.longitude.to_numpy())
phi=np.deg2rad(lat[ki])[:,None];lam=np.deg2rad(lon[ki])[:,None]
h=np.sin((phi-alat)/2)**2+np.cos(phi)*np.cos(alat)*np.sin((lam-alon)/2)**2
dist=6371*2*np.arcsin(np.sqrt(np.clip(h,0,1)));nearest=dist.argmin(axis=1)
matched=asosmeta.station_id.to_numpy()[nearest];distance=dist[np.arange(len(ki)),nearest]
pair=pd.DataFrame({'airkorea_station_code':stations[ki],'asos_station_id':matched,'distance_km':distance,'airkorea_latitude':lat[ki],'airkorea_longitude':lon[ki]})
pair.to_csv(OUT/'asos_station_linkage.csv',index=False,encoding='utf-8-sig')
asosvars=['wind_speed_ms','u_obs_ms','v_obs_ms','temperature_c','dewpoint_c','relative_humidity_pct','station_pressure_hpa','sea_level_pressure_hpa','precipitation_reported_mm','precipitation_interval_hours','solar_radiation_mj_m2','row_present']
annual={v:np.full((T,S),np.nan,dtype='float32') for v in asosvars}
for file in sorted(Path('outputs/ASOS_2020_processed/parquet').glob('*.parquet')):
    df=pd.read_parquet(file,columns=['step_g','station_id']+asosvars)
    ts=np.sort(df.step_g.unique())
    for v in asosvars:
        table=df.pivot(index='step_g',columns='station_id',values=v).reindex(index=ts,columns=matched)
        annual[v][np.ix_(ts,ki)]=table.to_numpy(dtype='float32')
    print('ASOS',file.name,flush=True)
for v,a in annual.items():append('asos_'+v,a,'see ASOS_2020_processed metadata; reported RN winter=3h, summer=1h')
distance_grid=np.broadcast_to(np.where(known,np.nan,np.nan),(T,S)).copy().astype('float32');distance_grid[:,ki]=distance
append('asos_distance_km',distance_grid,'km');del annual,distance_grid

# Satellite input has only grid-node index geometry. Scatter high-QA observations to original grid nodes
# by the provided weights, then bilinearly sample those grid-node means at the station.
# The observation's step_g is an integer-hour bin, not an exact overpass timestamp.
sat=np.full((T,S),np.nan,dtype='float32');qa=sat.copy();support=sat.copy();low=sat.copy()
yi=np.floor((lat[ki]-33)/.25).astype(int);xi=np.floor((lon[ki]-124)/.25).astype(int)
yi=np.clip(yi,0,39);xi=np.clip(xi,0,31)
fy=(lat[ki]-(33+yi*.25))/.25;fx=(lon[ki]-(124+xi*.25))/.25
nodes=[yi*33+xi,yi*33+xi+1,(yi+1)*33+xi,(yi+1)*33+xi+1]
weights=[(1-fy)*(1-fx),(1-fy)*fx,fy*(1-fx),fy*fx]
sat_info=[]
with zipfile.ZipFile(ROOT/'no2_korean_peninsula_2020.zip') as z:
    files=sorted(n for n in z.namelist() if '/netcdf/' in n and n.endswith('.nc') and not n.startswith('__'))
    assert len(files)==12
    for file in files:
        nc=netCDF4.Dataset('memory',memory=z.read(file));g=nc.groups['trop_hi'];lo=nc.groups['trop_lo']
        ts=np.asarray(g['step_g'][:],dtype=int);lt=np.asarray(lo['step_g'][:],dtype=int)
        month=int(file[-5:-3]);start=int((pd.Timestamp(2020,month,1)-pd.Timestamp('2020-01-01'))/pd.Timedelta(hours=1));end=int((pd.Timestamp(2020,month,1)+pd.offsets.MonthBegin(1)-pd.Timestamp('2020-01-01'))/pd.Timedelta(hours=1));nt=end-start
        assert np.all((ts>=start)&(ts<end)) and np.all((lt>=start)&(lt<end))
        val=np.ma.filled(g['no2'][:],np.nan).astype(float);q=np.ma.filled(g['qa'][:],np.nan).astype(float)
        sums=np.zeros(nt*1353);qsum=sums.copy();den=sums.copy()
        for k in range(4):
            node=np.asarray(g[f'n{k}'][:],dtype=int);w=np.asarray(g[f'w{k}'][:],dtype=float)
            iy=node//201-52;ix=node%201-96
            ok=(iy>=0)&(iy<=40)&(ix>=0)&(ix<=32)&np.isfinite(val)&np.isfinite(q)&np.isfinite(w)&(w>0)
            key=(ts[ok]-start)*1353+iy[ok]*33+ix[ok]
            sums+=np.bincount(key,weights=val[ok]*w[ok],minlength=len(sums));qsum+=np.bincount(key,weights=q[ok]*w[ok],minlength=len(sums));den+=np.bincount(key,weights=w[ok],minlength=len(sums))
        grid=np.divide(sums,den,out=np.full_like(sums,np.nan),where=den>0).reshape(nt,1353)
        qgrid=np.divide(qsum,den,out=np.full_like(sums,np.nan),where=den>0).reshape(nt,1353);den=den.reshape(nt,1353)
        numerator=np.zeros((nt,len(ki)));qnum=numerator.copy();wsum=numerator.copy();sup=numerator.copy()
        for node,w in zip(nodes,weights):
            v=grid[:,node];qq=qgrid[:,node];good=np.isfinite(v)
            numerator+=np.where(good,v,0)*w; qnum+=np.where(good,qq,0)*w;wsum+=good*w;sup+=den[:,node]*w
        sampled=np.divide(numerator,wsum,out=np.full_like(numerator,np.nan),where=wsum>0)
        sampledqa=np.divide(qnum,wsum,out=np.full_like(qnum,np.nan),where=wsum>0)
        sat[start:end,ki]=sampled;qa[start:end,ki]=sampledqa;support[start:end,ki]=sup
        ln=np.asarray(lo['node'][:],dtype=int);ly=ln//201-52;lx=ln%201-96;ok=(ly>=0)&(ly<=40)&(lx>=0)&(lx<=32)
        counts=np.bincount((lt[ok]-start)*1353+ly[ok]*33+lx[ok],minlength=nt*1353).reshape(nt,1353)
        nearby=np.zeros((nt,len(ki)),dtype=bool)
        for node,w in zip(nodes,weights):nearby|=(counts[:,node]>0)&(w[None,:]>0)
        low[start:end,ki]=nearby.astype('float32')
        sat_info.append({'month':month,'high_quality_observations':len(ts),'low_quality_mask_rows':len(lt),'negative_high_QA_columns_retained':int((val<0).sum())})
        nc.close();print('TROPOMI',file,flush=True)
append('satellite_no2_same_hour_mol_m2',sat,'mol m-2; native column, not ground ppb')
append('satellite_qa_same_hour',qa,'1')
append('satellite_weight_support',support,'sum of original pixel-node weights, not independent observation count')
append('satellite_low_quality_nearby',low,'0/1 low-quality source mask in station interpolation nodes')
available=np.where(np.isfinite(sat),1,0).astype('float32');available[:,~known]=np.nan
append('satellite_same_hour_available',available,'0/1')
# Carry only a past high-quality satellite value for <=24h. Never backfill or use a future day.
last=np.full_like(sat,np.nan);age=np.full_like(sat,np.nan);lastq=np.full_like(sat,np.nan)
laststep=np.full(S,-100000,dtype=int);lastval=np.full(S,np.nan);lastqa=np.full(S,np.nan)
for t in range(T):
    good=np.isfinite(sat[t]);laststep[good]=t;lastval[good]=sat[t,good];lastqa[good]=qa[t,good]
    valid=(t-laststep<=24)&known
    last[t,valid]=lastval[valid];age[t,valid]=t-laststep[valid];lastq[t,valid]=lastqa[valid]
    assert np.all(age[t,valid]>=0)
append('satellite_recent_24h_no2_mol_m2',last,'mol m-2; current or previous hour-bin only, max age 24h')
append('satellite_recent_age_hours',age,'hours')
append('satellite_recent_qa',lastq,'1')
del sat,qa,support,low,last,age,lastq
X=np.column_stack([old['X']]+features).astype('float32');assert X.shape[1]==len(names)
assert not np.isinf(X).any();assert np.array_equal(X[:,:9],old['X'],equal_nan=True)
np.savez_compressed(OUT/'training_arrays.npz',X=X,y=old['y'],split=old['split'],valid=old['valid'],station_id=old['station_id'],source_time_label=old['source_time_label'],coordinate_available=old['coordinate_available'])
for name,a in zip(names[9:],features):master[name]=a
master.to_parquet(OUT/'urban_no2_2020_fusion_master.parquet',index=False)
pd.DataFrame([{'feature':k,**v,'unit':units[k]} for k,v in coverage.items()]).to_csv(OUT/'feature_coverage.csv',index=False)
for name in ['no2_korean_peninsula_2020.zip','era5_korean_peninsula_2020.zip']:sources.append({'file':str(ROOT/name),'sha256':hashlib.sha256((ROOT/name).read_bytes()).hexdigest()})
meta.update(features=names,scope='Time + current coordinates + ERA5 + ASOS + TROPOMI',external_sources=sources,feature_units=units,feature_coverage=coverage,satellite_months=sat_info,UTC_outside_2020_rows=int((~in_year).sum()),ASOS_distance_summary_km={'min':float(distance.min()),'median':float(np.median(distance)),'max':float(distance.max())},matching={'ERA5':'bilinear per group sorted coordinates; original UTC time decoded per month; native units retained','ASOS':'nearest reference-coordinate station among 2020 data IDs with coordinates; no distance cutoff; exact UTC label; missing stays NaN','TROPOMI':'high-QA original weights scatter to 0.25deg nodes, weighted station interpolation renormalized over available nodes; low-QA mask only; integer hour-bin; past-only carry <=24h','AirKorea':'original KST label normalized hour24 then minus9h; averaging interval not shifted or independently verified','boundaries':'Before UTC2020 external features stay NaN, source target rows retained'},excluded_ERA5_variables={'z850_anom':'upstream anomaly reference/calibration definition unavailable; z850 and thk retained instead'},limitations=['Current AirKorea coordinates used without historical checks by user request','ASOS reference coordinates/heights also not historically verified','TROPOMI original pixel coordinates and exact overpass time unavailable; node/hour proxy used','ERA5 source variable units absent in processed NetCDF; native values preserved, u_pbl/v_pbl not called 10m wind','Station/time splits unchanged; designed spatial holdout not run','Source ERA5 z850_anom excluded because reference definition unavailable'])
(OUT/'data_metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
print('FUSION READY',X.shape,'external outside UTC year rows',int((~in_year).sum()),flush=True)
