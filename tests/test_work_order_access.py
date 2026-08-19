from uuid import UUID

from fieldservice_login.work_order_access import (
    DispatchStatus,
    WorkOrder,
    WorkOrderPhoto,
    record_site_visit,
)


def test_site_visit_with_follow_up_stays_open_for_technician_action() -> None:
    order = WorkOrder(
        work_order_id=UUID("10000000-0000-0000-0000-000000000001"),
        technician_id=UUID("20000000-0000-0000-0000-000000000002"),
        dispatch_status=DispatchStatus.ON_SITE,
    )
    photo = WorkOrderPhoto(
        photo_id=UUID("30000000-0000-0000-0000-000000000003"),
        object_key="orders/100/site-panel.jpg",
        captured_at="2026-08-18T09:30:00Z",
    )

    updated = record_site_visit(order, [photo], "Replace filter after lab review")

    assert updated.dispatch_status is DispatchStatus.FOLLOW_UP
    assert updated.photos == [photo]
    assert updated.follow_up is not None
    assert updated.follow_up.note == "Replace filter after lab review"
    assert order.dispatch_status is DispatchStatus.ON_SITE
