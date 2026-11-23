from fastapi import APIRouter, Depends, HTTPException, Query, Request
from common.events import DomainEvent
from common.security import Actor, current_actor, require_service_key

router=APIRouter()


@router.get("/health", tags=["Состояние"])
def health(request:Request):
    request.app.state.repo.health()
    return {"status":"ok","service":"notification"}


@router.post("/events",status_code=202,tags=["События"],dependencies=[Depends(require_service_key)])
def accept_event(request:Request,event:DomainEvent):
    return request.app.state.notification_service.handle_event(event)


@router.get("/notifications", tags=["Уведомления"])
def get_notifications(request:Request,department:int|None=Query(None,gt=0),
                      employee:int|None=Query(None,gt=0), unread:bool=False,
                      limit:int=Query(100,ge=1,le=500),actor:Actor=Depends(current_actor)):
    return request.app.state.repo.list(actor,department,employee,unread,limit)


@router.post("/notifications/{notification_id}/read",tags=["Уведомления"])
def mark_read(request:Request,notification_id:int,actor:Actor=Depends(current_actor)):
    result=request.app.state.repo.mark_read(actor,notification_id)
    if result is None:
        raise HTTPException(status_code=404,detail="Notification not found")
    if result is False:
        raise HTTPException(status_code=403,detail="Notification belongs to another department")
    return result
