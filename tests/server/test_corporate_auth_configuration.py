from server.eoat_api.corporate_auth import corporate_provider_state


def test_unselected_provider_fails_closed_without_claiming_rehearsal_is_enterprise_authentication():
    state = corporate_provider_state({})

    assert state.provider is None
    assert state.state == "UNAVAILABLE"
    assert not state.administrator_group_mapping_configured
    assert "approved corporate provider" in state.detail


def test_unapproved_provider_is_misconfigured_not_silently_accepted():
    state = corporate_provider_state({"EOAT_AUTH_PROVIDER": "saml"})

    assert state.provider is None
    assert state.state == "MISCONFIGURED"
    assert not state.administrator_group_mapping_configured


def test_kerberos_form_missing_required_inputs_is_misconfigured_without_disclosing_values():
    state = corporate_provider_state({"EOAT_AUTH_PROVIDER": "kerberos_form"})

    assert state.provider == "kerberos_form"
    assert state.state == "MISCONFIGURED"
    assert "EOAT_KERBEROS_REALM" in state.missing_configuration_names
    assert "EOAT_KERBEROS_MIN_SASL_SSF" in state.missing_configuration_names


def test_configured_provider_is_not_reported_ready_without_verified_provider_probe():
    environment = {"EOAT_AUTH_PROVIDER": "kerberos_form"}
    environment.update(
        {
            "EOAT_AUTH_SCOPE": "application",
            "EOAT_KERBEROS_REALM": "configured",
            "EOAT_KERBEROS_BASE_DN": "configured",
            "EOAT_KERBEROS_CACHE_DIRECTORY": "configured",
            "EOAT_KERBEROS_LOGIN_TIMEOUT_SECONDS": "configured",
            "EOAT_KERBEROS_MIN_SASL_SSF": "configured",
        }
    )

    state = corporate_provider_state(environment)

    assert state.provider == "saml"
    assert state.state == "UNKNOWN"
    assert not state.administrator_group_mapping_configured
    assert not state.missing_configuration_names
