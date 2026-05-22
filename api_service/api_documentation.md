# Cognithor - API Documentation

## Overview
This document provides comprehensive documentation for the Cognithor backend API, detailing all available endpoints, their functionality, request/response formats, authentication requirements, and usage examples.

## Base URL
The base URL for the API is dynamically configured and stored in the `api_config` database table. It defaults to `http://localhost:8000`, but can be changed by updating the `api_host` and `api_port` entries in the database via the onboarding script or directly.

## Authentication
The API uses JWT (JSON Web Token) authentication. Clients must first obtain a token via the `POST /token` endpoint, then include it in subsequent requests as a Bearer token in the `Authorization` header.

Users are stored in the `api_users` table of the Cognithor database. A default admin user (`admin`/`admin`) is created during onboarding.

## API Endpoints

### 0. Root Endpoint
Returns basic information about the API.

**Endpoint:** `GET /`

**Authentication:** Not required

**Response (200 OK):**
```json
{
  "message": "Cognithor API",
  "status": "running",
  "version": "0.1.0",
  "timestamp": "2026-05-22T22:00:00Z"
}
```

### 1. Health Check Endpoint
Returns the current health status of the application.

**Endpoint:** `GET /health`

**Authentication:** Not required

**Response (200 OK):**
```json
{
  "status": "healthy",
  "timestamp": "2026-05-22T22:00:00Z",
  "version": "0.1.0"
}
```

**Possible Status Values:**
- `healthy`: Application is running and responding.

### 2. Authentication Endpoint
Used to obtain a JWT access token.

**Endpoint:** `POST /token`

**Authentication:** Not required

**Request Body (Form Data - `application/x-www-form-urlencoded`):**
```
username=admin&password=admin
```

**Note:** The `username` and `password` should be sent as form-urlencoded data, not JSON. The password is transmitted as plaintext and hashed on the server using bcrypt.

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Error Responses:**
- `401 Unauthorized`: Incorrect username or password.

### 3. Get Current User Endpoint
Returns information about the currently authenticated user.

**Endpoint:** `GET /users/me`

**Authentication:** Required (Bearer token)

**Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Response (200 OK):**
```json
{
  "username": "admin"
}
```

**Error Responses:**
- `401 Unauthorized`: Invalid or missing token.

## Response Format
All API responses follow a consistent JSON format:

- Successful responses return appropriate HTTP status codes (200) with JSON data.
- Error responses return appropriate HTTP status codes with JSON error details.
- All timestamps are in ISO 8601 format (UTC).

## Error Handling
The API uses standard HTTP status codes:

- `200 OK`: Successful request.
- `401 Unauthorized`: Authentication required or failed.
- `404 Not Found`: Resource not found.
- `422 Unprocessable Entity`: Invalid request data.
- `500 Internal Server Error`: Server error.

Error responses include a `detail` field with a descriptive message:
```json
{
  "detail": "Incorrect username or password"
}
```

## Security Considerations
1. **HTTPS:** All API communication should occur over HTTPS in production.
2. **JWT Security:** JWT tokens should be stored securely by clients. Tokens have a limited lifespan (default 60 minutes, configurable via `access_token_expire_minutes` in the database).
3. **Secret Key:** The JWT signing key is auto-generated and stored in the `api_config` database table. It is never exposed via the API.
4. **Default Credentials:** The default admin user (`admin`/`admin`) is created during onboarding. Change this password immediately in production.
5. **Data Encryption:** The database supports optional SQLCipher encryption via `pysqlcipher3`.
6. **Configuration Storage:** All API configuration (host, port, secret key, algorithm, token expiry) is stored in the `api_config` table of the Cognithor database — no `.env` files are used.

## Quickstart

### 1. Initialize databases
```bash
cd cognithor/
python onboarding/setup.py init --no-encrypt
```

### 2. Start the API server
```bash
python -m api_service.main
# or
uvicorn api_service.main:app --host 0.0.0.0 --port 8000
```

### 3. Test connectivity
```bash
curl http://localhost:8000/health
```

### 4. Login and get a token
```bash
curl -X POST http://localhost:8000/token \
  -d "username=admin&password=admin"
```

### 5. Authenticated request
```bash
curl http://localhost:8000/users/me \
  -H "Authorization: Bearer <your_token>"
```
