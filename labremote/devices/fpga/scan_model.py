"""Pure scan geometry and Gaussian coupling-profile fits (coordinates in µm)."""
import warnings
import numpy as np
from scipy.optimize import curve_fit, OptimizeWarning


def axis_points(start, stop, step):
    if not all(np.isfinite(v) for v in (start, stop, step)) or step <= 0 or stop <= start:
        raise ValueError('축 범위는 start < stop, step > 0이어야 합니다.')
    intervals = (stop - start) / step
    if not np.isclose(intervals, round(intervals), rtol=0, atol=1e-6):
        raise ValueError('범위 길이가 step의 정수배여야 합니다.')
    if not 2 <= round(intervals) <= 1000:
        raise ValueError('축별 3–1001개 위치를 지정하세요.')
    return np.linspace(start, stop, round(intervals) + 1)


def gaussian(coords, background, amplitude, x0, y0, wx, wy, theta=0.):
    """1/e² radii; theta in radians, counterclockwise from +X."""
    x,y=coords
    u=(x-x0)*np.cos(theta)+(y-y0)*np.sin(theta)
    v=-(x-x0)*np.sin(theta)+(y-y0)*np.cos(theta)
    return background+amplitude*np.exp(-2*((u/wx)**2+(v/wy)**2))


def ellipse_geometry(fit):
    """Major/minor diameter and angle, also accepting previous saved fits."""
    if 'coupling_mfd_major_um' in fit:
        return fit['coupling_mfd_major_um'],fit['coupling_mfd_minor_um'],fit['angle_deg']
    x,y=fit['coupling_mfd_x_um'],fit['coupling_mfd_y_um']
    return (x,y,0.) if x>=y else (y,x,90.)


def fit_mfd(xs,ys,counts):
    xs=np.asarray(xs,dtype=float);ys=np.asarray(ys,dtype=float);z=np.asarray(counts,dtype=float)
    if z.shape!=(len(ys),len(xs)) or not np.all(np.isfinite(z)):
        raise ValueError('완료된 scan만 MFD fitting 가능합니다.')
    if len(xs)<5 or len(ys)<5 or np.ptp(z)<=0:
        raise ValueError('MFD fitting에는 각 축 5점 이상과 변화하는 신호가 필요합니다.')
    if not np.all(np.isfinite(xs)) or not np.all(np.isfinite(ys)) or np.any(np.diff(xs)<=0) or np.any(np.diff(ys)<=0):
        raise ValueError('Scan coordinates must be finite and increasing')
    # Center coordinates to avoid loss of precision at large absolute positions.
    ox,oy=float(xs.mean()),float(ys.mean());xx,yy=np.meshgrid(xs-ox,ys-oy)
    dx,dy=float(np.min(np.diff(xs))),float(np.min(np.diff(ys)))
    spanx,spany=float(np.ptp(xs)),float(np.ptp(ys))
    weights=np.maximum(z-z.min(),0);total=weights.sum()
    cx,cy=float((weights*xx).sum()/total),float((weights*yy).sum()/total)
    moment=np.array([[(weights*(xx-cx)**2).sum(),(weights*(xx-cx)*(yy-cy)).sum()],
                     [(weights*(xx-cx)*(yy-cy)).sum(),(weights*(yy-cy)**2).sum()]])/total
    eigen,vectors=np.linalg.eigh(moment);direction=vectors[:,1]
    theta=float(np.arctan2(direction[1],direction[0]));theta=(theta+np.pi/2)%np.pi-np.pi/2
    lo=min(dx,dy)/4;hi=2*np.hypot(spanx,spany)
    widths=np.clip(2*np.sqrt(np.maximum(eigen[::-1],0)),lo*1.01,hi*.99)
    guess=[max(0,float(z.min())),float(np.ptp(z)),cx,cy,*widths,theta]
    lower=[0,0,xs[0]-ox,ys[0]-oy,lo,lo,-np.pi]
    upper=[np.inf,np.inf,xs[-1]-ox,ys[-1]-oy,hi,hi,np.pi]
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',OptimizeWarning)
        pars,cov=curve_fit(gaussian,(xx.ravel(),yy.ravel()),z.ravel(),p0=guess,
                           bounds=(lower,upper),maxfev=20000,x_scale='jac')
    predicted=gaussian((xx,yy),*pars)
    r2=1-float(np.sum((z-predicted)**2)/np.sum((z-z.mean())**2))
    b,a,x0,y0,w1,w2,t=map(float,pars);x0+=ox;y0+=oy
    major,minor=(w1,w2) if w1>=w2 else (w2,w1)
    major_index,minor_index=(4,5) if w1>=w2 else (5,4)
    angle=(np.degrees(t)+(0 if w1>=w2 else 90))%180
    theta=np.radians(angle);co,si=np.cos(theta),np.sin(theta)
    # Keep old keys as axis-aligned center-section widths, not mislabeled principal axes.
    wx=1/np.sqrt(co**2/major**2+si**2/minor**2)
    wy=1/np.sqrt(si**2/major**2+co**2/minor**2)
    with np.errstate(invalid='ignore'):
        errors=np.sqrt(np.diag(cov))
    def finite(v):return float(v) if np.isfinite(v) else None
    angle_error=finite(np.degrees(errors[6]))
    reliable=major/minor>=1.05 and angle_error is not None and angle_error<30
    flags=[]
    if not reliable:flags.append('거의 원형이거나 각도 불확도가 큼: 회전각을 신뢰하기 어려움')
    if r2<.8:flags.append('낮은 R²: Gaussian 모델과 데이터가 잘 맞지 않음')
    ex=np.hypot(major*co,minor*si);ey=np.hypot(major*si,minor*co)
    if min(x0-xs[0],xs[-1]-x0)<ex or min(y0-ys[0],ys[-1]-y0)<ey:
        flags.append('스캔 범위가 회전된 1/e² 경계를 충분히 포함하지 않음')
    if minor<max(dx,dy):flags.append('step보다 작은 폭: 더 작은 step 필요')
    if not np.all(np.isfinite(errors[4:6])) or errors[major_index]>major/2 or errors[minor_index]>minor/2:
        flags.append('폭의 피팅 불확도가 큼')
    def section_std(axis):
        def width(p):
            c,s=np.cos(p[6]),np.sin(p[6])
            return 2/np.sqrt((c/p[4])**2+(s/p[5])**2) if axis=='x' else 2/np.sqrt((s/p[4])**2+(c/p[5])**2)
        jac=np.zeros(7)
        for i in (4,5,6):
            delta=1e-5*max(abs(pars[i]),1);plus=pars.copy();minus=pars.copy();plus[i]+=delta;minus[i]-=delta
            jac[i]=(width(plus)-width(minus))/(2*delta)
        if not np.all(np.isfinite(cov)):return None
        return finite(np.sqrt(max(0,float(jac@cov@jac))))
    return dict(model='rotated_elliptical_gaussian_v2',
        background=b,amplitude=a,x0_um=x0,y0_um=y0,
        w_major_um=major,w_minor_um=minor,coupling_mfd_major_um=2*major,coupling_mfd_minor_um=2*minor,
        angle_deg=float(angle),angle_std_deg=angle_error if reliable else None,angle_reliable=bool(reliable),
        angle_convention='Major axis counterclockwise from +X toward +Y, modulo 180 degrees',
        mfd_major_std_um=finite(2*errors[major_index]),mfd_minor_std_um=finite(2*errors[minor_index]),
        wx_um=float(wx),wy_um=float(wy),coupling_mfd_x_um=float(2*wx),coupling_mfd_y_um=float(2*wy),
        mfd_x_std_um=section_std('x'),mfd_y_std_um=section_std('y'),
        legacy_width_interpretation='X/Y center-section 1/e² diameters, not principal-axis diameters',
        r_squared=r2,warnings=flags,
        interpretation='Effective 1/e² coupling-profile diameter; not intrinsic fiber MFD without optical-mode calibration')


def fit_profiles(xs,ys,counts):
    """Return the rotated elliptical MFD fit or its failure for display and saving."""
    try:return fit_mfd(xs,ys,counts)
    except Exception as exc:return {'error':str(exc)}
