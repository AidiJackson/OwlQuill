#!/bin/bash
set -e

pip install -r backend/requirements.txt -q

cd backend
alembic upgrade head
