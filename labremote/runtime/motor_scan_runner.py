"""Absolute-coordinate XY/XYZ motor raster scan with queued FPGA measurements and partial saves."""
import csv
import json
import math
import time
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import numpy as np
from labremote.runtime.workflow_runner import WorkflowTask,motor_identity
from labremote.runtime.errors import OperationCancelled
from labremote.config.device_config import load_device_config,operation_config
from labremote.devices.fpga.scan_model import axis_points,fit_profiles


class MotorScanRunner(WorkflowTask):
    def __init__(self,worker,number):
        super().__init__(worker,'MOTOR_SCAN');self.number=number

    def start(self,x_motor,y_motor,settings,parent=None,*,z_motor=None):
        motors=[x_motor,y_motor]+([z_motor] if z_motor is not None else [])
        if any(api.worker.family!='motors' for api in motors):raise ValueError('Select Motor APIs')
        with operation_config():defaults=load_device_config('fpga',self.worker.name)['scan_defaults']
        defaults={**defaults,'pmt':self.number-1,'scan':self.number};unknown=set(settings)-set(defaults)
        config={**defaults,**settings}
        def run():
            if unknown:raise ValueError('Unknown scan settings: '+str(sorted(unknown)))
            if len({motor_identity(api.worker) for api in motors})!=len(motors):raise ValueError('Select distinct X, Y and Z motors')
            self.x_worker,self.y_worker=x_motor.worker,y_motor.worker
            self.z_worker=z_motor.worker if z_motor is not None else None
            return self.run_scan(config)
        return self.launch(run,(self.worker,*(api.worker for api in motors)),config,parent)

    def position(self,state):
        if state.get('online') is False:raise RuntimeError('Motor USB is closed or offline; Open the motor first')
        if state.get('status') not in ('completed','standby'):raise RuntimeError('Motor is not standby')
        value=state.get('position')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise RuntimeError('Motor position unavailable')
        return value

    def run_scan(self,c):
        from labremote.api.devices import device_api
        x=device_api(self.x_worker,group=self.group);y=device_api(self.y_worker,group=self.group);fpga=device_api(self.worker,group=self.group)
        xs=axis_points(c['x_start_um'],c['x_stop_um'],c['x_step_um']);ys=axis_points(c['y_start_um'],c['y_stop_um'],c['y_step_um'])
        z=device_api(self.z_worker,group=self.group) if self.z_worker is not None else None
        zs=axis_points(c['z_start_um'],c['z_stop_um'],c['z_step_um']) if z is not None else None
        if len(xs)*len(ys)*(len(zs) if zs is not None else 1)>100000:raise ValueError('Maximum 100000 scan points')
        for key in ('x_um_per_unit','y_um_per_unit','settle_ms','exposure_ms')+ (('z_um_per_unit',) if z is not None else ()):
            if isinstance(c[key],bool) or not isinstance(c[key],(int,float)) or not math.isfinite(c[key]):raise ValueError('Invalid scan setting: '+key)
        if min([c['x_um_per_unit'],c['y_um_per_unit']]+([c['z_um_per_unit']] if z is not None else []))<=0 or not 0<=c['settle_ms']<=60000:raise ValueError('Invalid scan scale/settle time')
        if type(c['average']) is not int or not 1<=c['average']<=100000:raise ValueError('Average N must be 1..100000')
        if not isinstance(c['directory'],str) or not c['directory'].strip():raise ValueError('Choose a save directory')
        origin=[self.position(self.call(x.status())),self.position(self.call(y.status()))]
        if z is not None:origin.append(self.position(self.call(z.status())))
        scales=[c['x_um_per_unit'],c['y_um_per_unit']]
        tolerance=[min(.001,c['x_step_um']/scales[0]*.25),min(.001,c['y_step_um']/scales[1]*.25)]
        base=Path(c['directory']).expanduser()
        if not base.is_absolute():base=Path(__file__).resolve().parents[2]/base
        folder=base/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+uuid4().hex[:6])
        folder.mkdir(parents=True,exist_ok=False)
        counts=np.full((len(zs),len(ys),len(xs)) if zs is not None else (len(ys),len(xs)),np.nan)
        config={**c,'x_motor':self.x_worker.name,'y_motor':self.y_worker.name,'initial_position_native':origin,'coordinate_mode':'absolute','x_positions_um':xs.tolist(),'y_positions_um':ys.tolist(),'position_observation':'readback/status after each move; no pre/post exposure polling','scan_order':'Y outer loop; X ascending with flyback'}
        config.update(z_motor=self.z_worker.name if self.z_worker is not None else None,z_positions_um=zs.tolist() if zs is not None else [],scan_order='Z outer, Y middle, X ascending with flyback' if z is not None else config['scan_order'])
        (folder/'configuration.json').write_text(json.dumps(config,indent=2,ensure_ascii=False),encoding='utf-8')
        self.publish(phase='STARTING',folder=str(folder),xs=xs.tolist(),ys=ys.tolist(),points=0,total=counts.size,scan=c['scan'],zs=zs.tolist() if zs is not None else [],iz=0)
        error=None;fit=None;fits=[];points=0;stop_errors=[];file=None
        try:
            file=(folder/'points.csv').open('x',newline='',encoding='utf-8-sig')
            fields=['timestamp','ix','iy','x_position_um','y_position_um','x_target_native','y_target_native','x_actual_native','y_actual_native','pmt','exposure_ms','average','pmt_counts','raw_counts']
            if z is not None:fields+=['iz','z_position_um','z_target_native','z_actual_native']
            writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader();file.flush()
            for iz,z_position in enumerate(zs if zs is not None else [None]):
                self.check();self.publish(phase='MOVING Z' if z is not None else 'STARTING XY',iz=iz,point=None)
                plane=counts[iz] if z is not None else counts
                if z is not None:
                    zt=z_position/c['z_um_per_unit']
                    z_tolerance=min(.001,c['z_step_um']/c['z_um_per_unit']*.25)
                    z_actual=self.position(self.call(z.move(zt,tolerance=z_tolerance)))
                for iy,dy in enumerate(ys):
                    self.check();yt=dy/scales[1]
                    self.publish(phase='MOVING Y',iy=iy)
                    y_actual=self.position(self.call(y.move(yt,tolerance=tolerance[1])))
                    for ix,dx in enumerate(xs):
                        self.check();xt=dx/scales[0]
                        self.publish(phase='MOVING X',ix=ix,iy=iy)
                        x_actual=self.position(self.call(x.move(xt,tolerance=tolerance[0])))
                        self.wait(c['settle_ms']/1000)
                        raw=[];actual=[x_actual,y_actual]
                        for sample in range(c['average']):
                            self.check()
                            self.publish(phase='MEASURING',sample=sample+1,average=c['average'])
                            value=self.call(fpga.measure(c['pmt'],c['exposure_ms']))
                            raw.append(value['count'])
                        count=float(np.mean(raw));plane[iy,ix]=count;points+=1
                        record=dict(timestamp=datetime.now().astimezone().isoformat(),ix=ix,iy=iy,x_position_um=dx,y_position_um=dy,x_target_native=xt,y_target_native=yt,x_actual_native=actual[0],y_actual_native=actual[1],pmt=c['pmt'],exposure_ms=value['ms'],average=len(raw),pmt_counts=count,raw_counts=json.dumps(raw))
                        if z is not None:record.update(iz=iz,z_position_um=float(z_position),z_target_native=zt,z_actual_native=z_actual)
                        writer.writerow(record)
                        file.flush();self.publish(phase='POINT',points=points,point=[ix,iy,count],iz=iz)
                self.check();self.publish(phase='FITTING',point=None)
                try:plane_fit=fit_profiles(xs,ys,plane)
                except Exception as exc:plane_fit={'error':str(exc)}
                fits.append(dict(iz=iz,z_um=float(zs[iz]) if z is not None else None,fit=plane_fit))
                self.publish(z_fits=fits if z is not None else [],fit=plane_fit)
            fit=fits[-1]['fit']
            self.check()
        except Exception as exc:
            error=exc;self.group.stop.set()
            self.publish(phase='STOPPING: saving partial scan')
            for worker in (self.x_worker,self.y_worker,*([self.z_worker] if self.z_worker is not None else [])):
                if worker._closing or worker.ps is None or worker.connection_error:
                    stop_errors.append(worker.name+': STOP not confirmed (disconnected/closing)');continue
                try:device_api(worker).stop().wait()
                except Exception as stop_error:stop_errors.append(worker.name+': '+str(stop_error))
        finally:
            if file is not None:
                try:file.close()
                except Exception as exc:
                    if error is None:error=exc
            status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error else 'completed'
            if error is None and self.handle.cancelled():
                error=OperationCancelled('Scan cancelled during finalization');status='cancelled'
            result=dict(status=status,reason=str(error) if error else '',points_completed=points,fit=fit if status=='completed' else None,z_fits=fits if status=='completed' and z is not None else [],stop_errors=stop_errors,configuration=config,folder=str(folder))
            save_errors=[]
            for save in (
                lambda:np.savez_compressed(folder/'heatmap.npz',x_um=xs,y_um=ys,counts=counts,**({'z_um':zs} if z is not None else {})),
                lambda:self.save_plots(folder,xs,ys,zs,counts,result),
            ):
                try:save()
                except Exception as exc:save_errors.append(str(exc))
            result['save_errors']=save_errors
            if save_errors and error is None:
                error=RuntimeError('Scan saving failed: '+'; '.join(save_errors));result.update(status='failed',reason=str(error))
            try:(folder/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
            except Exception as exc:
                if error is None:error=exc
                self.worker.failure.emit('SCAN_SAVE',str(exc))
            self.publish(phase=result['status'],result=result,fit=result['fit'],z_fits=result['z_fits'])
        if error is not None:raise error
        return result

    @classmethod
    def save_plots(cls,folder,xs,ys,zs,counts,result):
        if zs is None:return cls.save_plot(folder,xs,ys,counts,result['fit'])
        visited=[iz for iz in range(len(zs)) if np.isfinite(counts[iz]).any()]
        for iz in visited:
            fit=result['z_fits'][iz]['fit'] if result['z_fits'] else None
            cls.save_plot(folder,xs,ys,counts[iz],fit,filename=f'heatmap_z_{iz:04d}.png',title=f'Z = {zs[iz]:g} µm')
        selected=visited[-1] if visited else 0
        cls.save_plot(folder,xs,ys,counts[selected],result['fit'],title=f'Z = {zs[selected]:g} µm')

    @staticmethod
    def save_plot(folder,xs,ys,counts,fit,filename='heatmap.png',title=''):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.patches import Ellipse
        figure=Figure(figsize=(7,5),facecolor='white');FigureCanvasAgg(figure);axes=figure.add_subplot(111);axes.set_facecolor('white');axes.tick_params(colors='black')
        dx,dy=xs[1]-xs[0],ys[1]-ys[0]
        image=axes.imshow(np.ma.masked_invalid(counts),origin='lower',aspect='equal',extent=[xs[0]-dx/2,xs[-1]+dx/2,ys[0]-dy/2,ys[-1]+dy/2])
        axes.set_xlabel('X position (um)',color='black');axes.set_ylabel('Y position (um)',color='black')
        colorbar=figure.colorbar(image,ax=axes);colorbar.set_label('PMT counts (mean)',color='black');colorbar.ax.tick_params(colors='black')
        if fit and 'error' not in fit:
            axes.plot(fit['x0_um'],fit['y0_um'],'r+')
            axes.add_patch(Ellipse((fit['x0_um'],fit['y0_um']),fit['coupling_mfd_x_um'],fit['coupling_mfd_y_um'],fill=False,edgecolor='white'))
        axes.set_title(title,color='black');figure.tight_layout();figure.savefig(folder/filename,dpi=160)
