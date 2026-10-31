from labremote.api.devices import DeviceAPI
from labremote.runtime.workflow_runner import WorkflowTask
from labremote.operation.flip.control import move
from labremote.operation.oven_relay.control import close_shutter
from .settings import load_settings


class FlipRouting:
    def __init__(self,workers,oven):
        self.workers,self.oven=workers,oven
        self.task=RouteTask(self)

    def plan(self,chamber,automatic=False):
        if chamber not in ('EA','EC'):raise ValueError('Chamber must be EA or EC')
        config=load_settings()
        if automatic and not config['auto_route']:return ()
        route=config['routes'].get(chamber,{})
        if not route:raise ValueError(chamber+' flipper mapping is not configured; no movement')
        if self.task.running():raise RuntimeError('Flipper routing is already running')
        plan=[]
        for name,position in sorted(route.items()):
            worker=self.workers[name]
            if worker.ps is None or worker.connection_error or worker.has_requests():
                raise ConnectionError('Connect idle '+name+' before routing')
            plan.append((name,position))
        return tuple(plan)


class RouteTask(WorkflowTask):
    def __init__(self,routing):
        self.routing=routing
        super().__init__(routing.oven.relays,'FLIP_ROUTE')

    def start(self,chamber):
        if self.routing.oven.task.running():raise RuntimeError('Stop oven loading before manual routing')
        plan=self.routing.plan(chamber)
        workers=[self.routing.workers[name] for name,_ in plan]
        return self.launch(self._execute,(self.worker,*workers),{'plan':plan,'chamber':chamber})

    def _execute(self):
        # Keep shutter closed on success as well; user/oven explicitly opens it.
        self.call(DeviceAPI(self.worker,group=self.group)._submit('FLIP_SHUTTER_CLOSE',lambda w:close_shutter(w.ps,'shutter_2')))
        for name,position in self.settings['plan']:
            self.check()
            self.call(DeviceAPI(self.routing.workers[name],group=self.group)._submit(
                'FLIP_ROUTE_MOVE',lambda w,p=position:move(w.ps,p)))
        return {'chamber':self.settings['chamber'],'shutter':'CLOSED'}
