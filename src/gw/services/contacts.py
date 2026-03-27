from __future__ import annotations

from typing import Any

import click

from gw.auth import build_service, execute_google_request
from gw.config import GWConfig
from gw.output import json_option, print_human, print_json, use_json_output


def _contacts_service(config: GWConfig | None = None):
    return build_service("people", "v1", config=config)


def _person_to_contact(person: dict[str, Any]) -> dict[str, Any]:
    names = person.get("names", [])
    emails = person.get("emailAddresses", [])
    phones = person.get("phoneNumbers", [])
    return {
        "resource_name": person.get("resourceName"),
        "name": names[0].get("displayName", "") if names else "",
        "emails": [item.get("value", "") for item in emails if item.get("value")],
        "phones": [item.get("value", "") for item in phones if item.get("value")],
    }


def search_contacts(
    query: str,
    max_results: int = 10,
    config: GWConfig | None = None,
) -> list[dict[str, Any]]:
    service = _contacts_service(config)
    execute_google_request(
        service.people().searchContacts(query="", readMask="names,emailAddresses,phoneNumbers")
    )
    response = execute_google_request(
        service.people().searchContacts(
            query=query,
            readMask="names,emailAddresses,phoneNumbers",
            pageSize=max_results,
        )
    )
    return [_person_to_contact(item.get("person", {})) for item in response.get("results", [])]


def list_contacts(max_results: int = 100, config: GWConfig | None = None) -> list[dict[str, Any]]:
    service = _contacts_service(config)
    response = execute_google_request(
        service.people()
        .connections()
        .list(
            resourceName="people/me",
            personFields="names,emailAddresses,phoneNumbers",
            pageSize=max_results,
        )
    )
    return [_person_to_contact(person) for person in response.get("connections", [])]


def _print_contacts(contacts: list[dict[str, Any]], label: str) -> None:
    if not contacts:
        print_human(f"No contacts found for {label}.", emoji="👥")
        return
    print_human(f"Contacts ({len(contacts)}):", emoji="👥")
    for contact in contacts:
        print_human(f"  • {contact['name'] or '(No name)'}")
        if contact["emails"]:
            print_human(f"    Emails: {', '.join(contact['emails'])}")
        if contact["phones"]:
            print_human(f"    Phones: {', '.join(contact['phones'])}")


def register_contacts_commands(group: click.Group) -> None:
    @group.command("search")
    @click.argument("query")
    @click.option("--max", "max_results", default=10, type=int, show_default=True)
    @json_option
    @click.pass_context
    def search_command(
        ctx: click.Context, query: str, max_results: int, json_output: bool | None
    ) -> None:
        contacts = search_contacts(query=query, max_results=max_results, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(contacts)
        else:
            _print_contacts(contacts, f"query {query!r}")

    @group.command("list")
    @click.option("--max", "max_results", default=100, type=int, show_default=True)
    @json_option
    @click.pass_context
    def list_command(ctx: click.Context, max_results: int, json_output: bool | None) -> None:
        contacts = list_contacts(max_results=max_results, config=ctx.obj["config"])
        if use_json_output(ctx, json_output):
            print_json(contacts)
        else:
            _print_contacts(contacts, "all contacts")
