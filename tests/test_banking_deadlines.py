import pytest

from src.banking_service.deadlines import LEGACY,LEARNED,profile


def test_learned_profile_orders_entire_timeout_chain_without_changing_default():
    assert profile() is LEGACY and LEGACY.actor_store==15 and LEGACY.ticket==30
    value=profile("learned-guard-v1")
    assert value is LEARNED
    assert value.reviewer<value.native_hook<value.actor_store
    # A claim can take the entire timeout, followed by a bounded tool worker and
    # commit; the outer Actor deadline must cover both, not only admission.
    assert value.actor_store+15+5<value.actor_server<value.actor_client<value.mcp_client<value.mcp_route<value.ticket
    with pytest.raises(ValueError):profile("typo")


@pytest.mark.parametrize("lifetime",[0,91,True,30.5])
def test_ticket_lifetime_rejects_invalid_configuration(tmp_path,lifetime):
    from src.banking_service.store import StateStore
    from src.banking_contracts.codec import ContractError
    with pytest.raises(ContractError,match="invalid_ticket_lifetime"):
        StateStore(tmp_path/"unused.sqlite",b"k"*32,catalog=object(),ticket_lifetime=lifetime)
