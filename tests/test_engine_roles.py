"""Roles on gates (GEN-27): the deployment's map of roles to people, the owner's by default, and the app's answer
when a decision comes from outside a role."""
from engine import roles as RL


def test_every_role_is_the_owners_at_home_and_a_deployment_maps_roles_to_its_people(tmp_path, monkeypatch):
    assert RL.people("spec-approver", tmp_path / "none.yaml") == ["owner"]
    f = tmp_path / "roles.yaml"
    f.write_text("default: [lead]\nroles: {legal: [lena, lars]}\n")
    assert RL.people("legal", f) == ["lena", "lars"] and RL.people("anything", f) == ["lead"]
    assert RL.may("legal", "lars", f) and not RL.may("legal", "lead", f)
    monkeypatch.setenv("AISTACK_ROLES", str(f))
    assert RL.people("legal") == ["lena", "lars"]


def test_the_repositorys_roles_file_names_no_person():
    roles, default = RL.load(RL.ROOT / "config/roles.yaml")
    assert default == ["owner"] and roles == {}
