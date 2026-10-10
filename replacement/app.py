"""Aplicación WSGI del reemplazo.

La autenticación se evalúa antes del ruteo y clasifica cada solicitud como
``valid``, ``missing`` o ``invalid`` sin revelar el valor recibido. Con el
catálogo listo y credencial válida, ``POST /msg`` responde de forma provisional
``503`` con el texto literal ``aún no disponible``; el resto de las rutas se
resuelven con la respuesta de referencia correspondiente.
"""

from __future__ import annotations

from flask import Flask, Response, request

from .references import Catalog, TEXT_CONTENT_TYPE, load_catalog, unavailable_catalog
from .settings import DEFAULT_REFERENCES_PATH, Settings, load_settings
from .state import TemporaryState

STUB_STATUS = 503
STUB_BODY = "aún no disponible"

# Métodos estándar atendidos por la ruta catch-all; los no listados se atienden
# desde los manejadores de error para no emitir respuestas del framework.
ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"]

MANIFEST_PATH = "reference_cases.json"


def classify_auth(header: str | None, expected_token: str) -> str:
    """Clasifica la credencial en ``valid``, ``missing`` o ``invalid``."""
    if header is None:
        return "missing"
    prefix = "Bearer "
    if not header.startswith(prefix):
        return "invalid"
    token = header[len(prefix):]
    if not expected_token or token != expected_token:
        return "invalid"
    return "valid"


def create_app(settings: Settings, catalog: Catalog, state: TemporaryState | None = None) -> Flask:
    """Construye la aplicación con dependencias explícitas."""
    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    base_state = state if state is not None else TemporaryState()

    def is_ready() -> bool:
        return bool(settings.ready and catalog.ready)

    def blocked_reason() -> str:
        if not settings.ready:
            return settings.reason or "configuración no disponible"
        return catalog.reason or "catálogo de referencias no disponible"

    def blocked(message: str) -> Response:
        return Response(f"base no lista: {message}\n", status=503, content_type=TEXT_CONTENT_TYPE)

    def handle() -> Response:
        auth = classify_auth(request.headers.get("Authorization"), settings.token)

        if not is_ready():
            return blocked(blocked_reason())

        if request.method == "POST" and request.path == "/msg" and auth == "valid":
            return Response(STUB_BODY, status=STUB_STATUS, content_type=TEXT_CONTENT_TYPE)

        reference = catalog.resolve(request.method, request.path, auth)
        if reference is None:
            return blocked(
                f"sin respuesta de referencia para {request.method} {request.path} ({auth})"
            )

        if request.method == "POST" and request.path == "/__reset" and auth == "valid":
            base_state.reset()

        return Response(reference.body, status=reference.status, content_type=reference.content_type)

    @app.route("/", methods=ALL_METHODS, provide_automatic_options=False)
    @app.route("/<path:subpath>", methods=ALL_METHODS, provide_automatic_options=False)
    def _catch_all(subpath: str = "") -> Response:  # noqa: ARG001 - ruta capturada
        return handle()

    @app.errorhandler(404)
    @app.errorhandler(405)
    def _unmatched(_error) -> Response:  # noqa: ANN001 - firma requerida por Flask
        return handle()

    @app.errorhandler(500)
    def _internal(_error) -> Response:  # noqa: ANN001 - firma requerida por Flask
        return Response("base no lista: error interno\n", status=500, content_type=TEXT_CONTENT_TYPE)

    return app


def build_app() -> Flask:
    """Construye la aplicación de producción desde el entorno."""
    try:
        settings = load_settings()
        catalog = load_catalog(settings, MANIFEST_PATH)
    except Exception:  # pragma: no cover - salvaguarda de arranque
        settings = Settings(
            token="",
            references_path=DEFAULT_REFERENCES_PATH,
            ready=False,
            reason="no se pudo inicializar la configuración",
        )
        catalog = unavailable_catalog("no se pudo inicializar el catálogo de referencias")
    return create_app(settings, catalog)


app = build_app()
