import json
import logging

import click
from sqlalchemy import select

from apps.base import base as app
from main import db
from models.content import ContentTypeDefinition, ContentTypeFieldDefinition

logger = logging.getLogger(__name__)


@app.cli.command("load_content_types")
@click.option(
    "--file-name",
    default="config/content_types.json",
)
def load_content_types(file_name):
    with open(file_name) as data_file:
        logger.info(f"Loading content types from '{file_name}'")
        definitions = json.load(data_file)

    for type_def_name in definitions:
        type_def = db.session.scalar(
            select(ContentTypeDefinition).where(ContentTypeDefinition.name == type_def_name)
        )

        if type_def is None:
            type_def = ContentTypeDefinition(type_def_name)
            db.session.add(type_def)
            db.session.commit()
            logger.info(f"Added content type '{type_def_name}' id={type_def.id}")
        else:
            logger.info(f"Type '{type_def_name}' already exists, skipping.")

        for field_def_name in definitions[type_def_name]:
            field_def = db.session.scalar(
                select(ContentTypeFieldDefinition)
                .where(ContentTypeFieldDefinition.name == field_def_name)
                .where(ContentTypeFieldDefinition.type_id == type_def.id)
            )

            if field_def is None:
                field_def = ContentTypeFieldDefinition(
                    field_def_name,
                    type_def,
                    display_name=definitions[type_def_name].get("display_name", None),
                    default=definitions[type_def_name].get("default", None),
                )
                db.session.add(field_def)
                db.session.commit()
                logger.info(f"Added '{field_def_name}' field to '{type_def_name}' id={field_def.id}")
            else:
                logger.info(f"Field '{field_def_name}' already exists for {type_def_name}, skipping")
    logger.info("Finished loading content types")
