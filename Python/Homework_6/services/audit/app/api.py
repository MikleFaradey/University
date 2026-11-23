from fastapi import APIRouter, Depends, HTTPException, Query, Request
from common.events import DomainEvent
from common.security import Actor,current_actor,require_service_key

router=APIRouter()


@router.get("/health",tags=["Состояние"])
def health(request:Request):
    request.app.state.repo.health()
    return {"status":"ok","service":"audit"}


@router.post("/events",status_code=202,tags=["События"],dependencies=[Depends(require_service_key)])
def accept_event(request:Request,event:DomainEvent):
    return request.app.state.audit_service.record(event)


@router.get("/audit",tags=["Аудит"])
def audit(request:Request,task_id:int|None=Query(None,gt=0),actor:int|None=Query(None,gt=0),
          limit:int=Query(100,ge=1,le=500),user:Actor=Depends(current_actor)):
    if user.role not in ("admin","manager"):
        raise HTTPException(status_code=403,detail="Manager or admin role required")
    return request.app.state.repo.list(user,task_id,actor,limit)
