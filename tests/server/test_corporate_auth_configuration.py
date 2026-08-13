from server.eoat_api.corporate_auth import corporate_provider_state


def test_unselected_provider_fails_closed_without_claiming_rehearsal_is_enterprise_authentication():
    state = corporate_provider_state({})

    assert state.provider is None
    assert state.state == "UNAVAILABLE"
    assert not state.administrator_group_mapping_configured
    assert "approved LDAPS or SAML" in state.detail


def test_unapproved_provider_is_misconfigured_not_silently_accepted():
    state = corporate_provider_state({"EOAT_CORPORATE_AUTH_PROVIDER": "kerberos_form"})

    assert state.provider is None
    assert state.state == "MISCONFIGURED"
    assert not state.administrator_group_mapping_configured


def test_ldaps_missing_required_inputs_is_misconfigured_without_disclosing_values():
    state = corporate_provider_state({"EOAT_CORPORATE_AUTH_PROVIDER": "ldaps"})

    assert state.provider == "ldaps"
    assert state.state == "MISCONFIGURED"
    assert "EOAT_LDAPS_HOSTS" in state.missing_configuration_names
    assert "EOAT_CORPORATE_ADMIN_GROUP" in state.missing_configuration_names


def test_configured_provider_is_not_reported_ready_without_verified_provider_probe():
    environment = {"EOAT_CORPORATE_AUTH_PROVIDER": "saml"}
    environment.update(
        {
            "EOAT_SAML_METADATA_URL": "configured",
            "EOAT_SAML_ENTITY_ID": "configured",
            "EOAT_SAML_ACS_URL": "configured",
            "EOAT_SAML_STABLE_SUBJECT_CLAIM": "configured",
            "EOAT_SAML_GROUPS_CLAIM": "configured",
            "EOAT_CORPORATE_ADMIN_GROUP": "configured",
        }
    )

    state = corporate_provider_state(environment)

    assert state.provider == "saml"
    assert state.state == "UNKNOWN"
    assert state.administrator_group_mapping_configured
    assert not state.missing_configuration_names
