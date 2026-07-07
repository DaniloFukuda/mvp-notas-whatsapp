import re
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path


DEFAULT_DB_PATH = Path("data/app.db")
VISITA_COLUMNS = (
    "id",
    "telefone_origem",
    "tecnico_nome",
    "fazenda",
    "proprietario",
    "telefone_proprietario",
    "gerente",
    "telefone_gerente",
    "area",
    "area_hectares",
    "area_alqueires",
    "safra",
    "tipo_visita",
    "descricao_visita",
    "objetivo",
    "observacoes",
    "observacoes_gerais",
    "status",
    "estado_fluxo",
    "data_visita",
    "latitude_principal",
    "longitude_principal",
    "maps_url_principal",
    "criado_em",
    "atualizado_em",
    "fechado_em",
)
VALID_REPORT_STATUSES = ("aberta", "fechada")


class VisitasTecnicasService:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS visitas_tecnicas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telefone_origem TEXT NOT NULL,
                    tecnico_nome TEXT,
                    fazenda TEXT,
                    proprietario TEXT,
                    telefone_proprietario TEXT,
                    gerente TEXT,
                    telefone_gerente TEXT,
                    area TEXT,
                    area_hectares REAL,
                    area_alqueires REAL,
                    safra TEXT,
                    tipo_visita TEXT,
                    descricao_visita TEXT,
                    objetivo TEXT,
                    observacoes TEXT,
                    observacoes_gerais TEXT,
                    status TEXT NOT NULL DEFAULT 'aberta',
                    estado_fluxo TEXT,
                    data_visita TEXT,
                    latitude_principal REAL,
                    longitude_principal REAL,
                    maps_url_principal TEXT,
                    criado_em TEXT NOT NULL,
                    atualizado_em TEXT,
                    fechado_em TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS visita_midias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visita_id INTEGER NOT NULL,
                    tipo TEXT,
                    media_id_whatsapp TEXT,
                    caminho_arquivo TEXT,
                    legenda TEXT,
                    latitude REAL,
                    longitude REAL,
                    maps_url TEXT,
                    indice INTEGER,
                    comentario TEXT,
                    comentario_status TEXT,
                    enviado_em TEXT,
                    FOREIGN KEY(visita_id) REFERENCES visitas_tecnicas(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS visita_localizacoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visita_id INTEGER NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    maps_url TEXT NOT NULL,
                    descricao TEXT,
                    enviado_em TEXT,
                    FOREIGN KEY(visita_id) REFERENCES visitas_tecnicas(id)
                )
                """
            )
            self._ensure_columns(
                connection,
                "visitas_tecnicas",
                {
                    "telefone_proprietario": "TEXT",
                    "telefone_gerente": "TEXT",
                    "area": "TEXT",
                    "descricao_visita": "TEXT",
                    "observacoes_gerais": "TEXT",
                },
            )
            self._ensure_columns(
                connection,
                "visita_midias",
                {
                    "indice": "INTEGER",
                    "comentario": "TEXT",
                    "comentario_status": "TEXT",
                    "storage_key": "TEXT",
                    "public_url": "TEXT",
                    "tamanho_bytes": "INTEGER",
                    "mime_type": "TEXT",
                },
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS visita_dados_coletados (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visita_id INTEGER NOT NULL,
                    chave TEXT NOT NULL,
                    valor TEXT,
                    observacao TEXT,
                    criado_em TEXT NOT NULL,
                    FOREIGN KEY(visita_id) REFERENCES visitas_tecnicas(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS visita_edicoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visita_id INTEGER NOT NULL,
                    telefone_editor TEXT,
                    campo TEXT NOT NULL,
                    valor_anterior TEXT,
                    valor_novo TEXT,
                    criado_em TEXT NOT NULL,
                    FOREIGN KEY(visita_id) REFERENCES visitas_tecnicas(id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_visitas_abertas_telefone
                ON visitas_tecnicas (telefone_origem, status, id)
                """
            )
            connection.commit()

    def iniciar_visita(
        self,
        telefone_origem: str,
        tecnico_nome: str | None = None,
    ) -> dict:
        self.ensure_schema()
        open_visit = self.obter_visita_aberta(telefone_origem)
        if open_visit is not None:
            return open_visit

        return self.criar_visita(telefone_origem, tecnico_nome=tecnico_nome)

    def criar_visita(
        self,
        telefone_origem: str,
        tecnico_nome: str | None = None,
        fazenda: str | None = None,
        estado_fluxo: str = "aguardando_fazenda",
    ) -> dict:
        self.ensure_schema()
        now = _now()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO visitas_tecnicas (
                    telefone_origem, tecnico_nome, fazenda, status, estado_fluxo,
                    data_visita, criado_em, atualizado_em
                ) VALUES (?, ?, ?, 'aberta', ?, ?, ?, ?)
                """,
                (
                    normalize_phone(telefone_origem),
                    _clean(tecnico_nome),
                    _clean(fazenda),
                    _clean(estado_fluxo),
                    date.today().isoformat(),
                    now,
                    now,
                ),
            )
            connection.commit()
            visita_id = cursor.lastrowid
        return self.obter_visita(visita_id) or {}

    def obter_visita_aberta(self, telefone_origem: str) -> dict | None:
        self.ensure_schema()
        phone = normalize_phone(telefone_origem)
        if not phone:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""
                SELECT {", ".join(VISITA_COLUMNS)}
                FROM visitas_tecnicas
                WHERE telefone_origem = ? AND status = 'aberta'
                ORDER BY id DESC
                LIMIT 1
                """,
                (phone,),
            ).fetchone()
        return dict(row) if row is not None else None

    def obter_visita(self, visita_id: int) -> dict | None:
        self.ensure_schema()
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""
                SELECT {", ".join(VISITA_COLUMNS)}
                FROM visitas_tecnicas
                WHERE id = ?
                """,
                (int(visita_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def atualizar_campo(self, visita_id: int, campo: str, valor) -> dict:
        allowed = {
            "tecnico_nome",
            "fazenda",
            "proprietario",
            "telefone_proprietario",
            "gerente",
            "telefone_gerente",
            "area",
            "area_hectares",
            "area_alqueires",
            "safra",
            "tipo_visita",
            "descricao_visita",
            "objetivo",
            "observacoes",
            "observacoes_gerais",
            "estado_fluxo",
            "data_visita",
            "latitude_principal",
            "longitude_principal",
            "maps_url_principal",
        }
        if campo not in allowed:
            raise ValueError("Campo de visita invalido.")
        safe_value = _to_float(valor) if campo in {"area_hectares", "area_alqueires", "latitude_principal", "longitude_principal"} else _clean(valor)
        return self._update_visita(visita_id, {campo: safe_value})

    def editar_campo(
        self,
        visita_id: int,
        campo: str,
        valor,
        telefone_editor: str | None = None,
    ) -> dict:
        visita = self.obter_visita(visita_id)
        if visita is None:
            raise ValueError("Visita nao encontrada.")
        if visita.get("status") not in VALID_REPORT_STATUSES:
            raise ValueError("Visita nao pode ser editada.")
        before = visita.get(campo)
        saved = self.atualizar_campo(visita_id, campo, valor)
        self.registrar_edicao(
            visita_id=visita_id,
            telefone_editor=telefone_editor,
            campo=campo,
            valor_anterior=before,
            valor_novo=saved.get(campo),
        )
        return {
            "visita": saved,
            "campo": campo,
            "valor_anterior": before,
            "valor_novo": saved.get(campo),
        }

    def registrar_edicao(
        self,
        visita_id: int,
        telefone_editor: str | None,
        campo: str,
        valor_anterior,
        valor_novo,
    ) -> dict:
        self.ensure_schema()
        now = _now()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO visita_edicoes (
                    visita_id, telefone_editor, campo, valor_anterior, valor_novo, criado_em
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(visita_id),
                    normalize_phone(telefone_editor),
                    _clean(campo),
                    _clean(valor_anterior),
                    _clean(valor_novo),
                    now,
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT id, visita_id, telefone_editor, campo, valor_anterior, valor_novo, criado_em
                FROM visita_edicoes
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return dict(row) if row is not None else {}

    def listar_edicoes(self, visita_id: int) -> list[dict]:
        self.ensure_schema()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, visita_id, telefone_editor, campo, valor_anterior, valor_novo, criado_em
                FROM visita_edicoes
                WHERE visita_id = ?
                ORDER BY criado_em, id
                """,
                (int(visita_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def descricao_da_visita(self, visita: dict) -> str:
        return _clean(visita.get("descricao_visita")) or _clean(visita.get("tipo_visita"))

    def adicionar_observacao(self, visita_id: int, texto: str) -> dict:
        visita = self.obter_visita(visita_id)
        if visita is None:
            raise ValueError("Visita nao encontrada.")
        text = _clean(texto)
        current = _clean(visita.get("observacoes"))
        combined = "\n".join(item for item in (current, text) if item)
        return self._update_visita(visita_id, {"observacoes": combined})

    def adicionar_observacao_geral(self, visita_id: int, texto: str) -> dict:
        visita = self.obter_visita(visita_id)
        if visita is None:
            raise ValueError("Visita nao encontrada.")
        text = _clean(texto)
        current = self.observacoes_gerais_lista(visita)
        if text:
            current.append(text)
        return self._update_visita(visita_id, {"observacoes_gerais": "\n".join(current)})

    def substituir_observacoes_gerais(self, visita_id: int, observacoes: list[str]) -> dict:
        clean_items = [_clean(item) for item in observacoes if _clean(item)]
        return self._update_visita(visita_id, {"observacoes_gerais": "\n".join(clean_items)})

    def observacoes_gerais_lista(self, visita: dict) -> list[str]:
        text = _clean(visita.get("observacoes_gerais")) or _clean(visita.get("observacoes"))
        return [line.strip() for line in text.splitlines() if line.strip()]

    def adicionar_dado_coletado(
        self,
        visita_id: int,
        chave: str,
        valor: str,
        observacao: str | None = None,
    ) -> dict:
        self.ensure_schema()
        safe_key = _clean(chave)
        if not safe_key:
            raise ValueError("Chave do dado coletado e obrigatoria.")
        now = _now()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO visita_dados_coletados (
                    visita_id, chave, valor, observacao, criado_em
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (int(visita_id), safe_key, _clean(valor), _clean(observacao), now),
            )
            connection.execute(
                "UPDATE visitas_tecnicas SET atualizado_em = ? WHERE id = ?",
                (now, int(visita_id)),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT id, visita_id, chave, valor, observacao, criado_em
                FROM visita_dados_coletados
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return dict(row) if row is not None else {}

    def adicionar_localizacao(
        self,
        visita_id: int,
        latitude: float,
        longitude: float,
        descricao: str | None = None,
    ) -> dict:
        self.ensure_schema()
        lat = float(latitude)
        lng = float(longitude)
        maps_url = self.gerar_maps_url(lat, lng)
        now = _now()
        visita = self.obter_visita(visita_id)
        if visita is None:
            raise ValueError("Visita nao encontrada.")
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO visita_localizacoes (
                    visita_id, latitude, longitude, maps_url, descricao, enviado_em
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (int(visita_id), lat, lng, maps_url, _clean(descricao), now),
            )
            updates = {"atualizado_em": now}
            if visita.get("latitude_principal") is None or not visita.get("maps_url_principal"):
                updates.update(
                    {
                        "latitude_principal": lat,
                        "longitude_principal": lng,
                        "maps_url_principal": maps_url,
                    }
                )
            assignments = ", ".join(f"{column} = ?" for column in updates)
            connection.execute(
                f"UPDATE visitas_tecnicas SET {assignments} WHERE id = ?",
                (*updates.values(), int(visita_id)),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT id, visita_id, latitude, longitude, maps_url, descricao, enviado_em
                FROM visita_localizacoes
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return dict(row) if row is not None else {}

    def adicionar_midia(
        self,
        visita_id: int,
        tipo: str,
        media_id_whatsapp: str | None = None,
        caminho_arquivo: str | None = None,
        legenda: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        storage_key: str | None = None,
        public_url: str | None = None,
        tamanho_bytes: int | None = None,
        mime_type: str | None = None,
    ) -> dict:
        self.ensure_schema()
        maps_url = (
            self.gerar_maps_url(float(latitude), float(longitude))
            if latitude is not None and longitude is not None
            else ""
        )
        now = _now()
        with closing(self._connect()) as connection:
            indice = self._next_media_index(connection, int(visita_id))
            cursor = connection.execute(
                """
                INSERT INTO visita_midias (
                    visita_id, tipo, media_id_whatsapp, caminho_arquivo, legenda,
                    latitude, longitude, maps_url, indice, comentario,
                    comentario_status, storage_key, public_url, tamanho_bytes,
                    mime_type, enviado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(visita_id),
                    _clean(tipo),
                    _clean(media_id_whatsapp),
                    _clean(caminho_arquivo),
                    _clean(legenda),
                    latitude,
                    longitude,
                    maps_url,
                    indice,
                    None,
                    "pendente" if _clean(tipo) in {"foto", "video"} else "",
                    _clean(storage_key),
                    _clean(public_url),
                    int(tamanho_bytes) if tamanho_bytes is not None else None,
                    _clean(mime_type),
                    now,
                ),
            )
            connection.execute(
                "UPDATE visitas_tecnicas SET atualizado_em = ? WHERE id = ?",
                (now, int(visita_id)),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT id, visita_id, tipo, media_id_whatsapp, caminho_arquivo,
                       legenda, latitude, longitude, maps_url, indice, comentario,
                       comentario_status, storage_key, public_url, tamanho_bytes,
                       mime_type, enviado_em
                FROM visita_midias
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return dict(row) if row is not None else {}

    def obter_midia(self, midia_id: int) -> dict | None:
        self.ensure_schema()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM visita_midias WHERE id = ?",
                (int(midia_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def contar_midias_por_tipo(self, visita_id: int, tipo: str) -> int:
        self.ensure_schema()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM visita_midias
                WHERE visita_id = ? AND tipo = ?
                """,
                (int(visita_id), _clean(tipo)),
            ).fetchone()
        return int((row or {"total": 0})["total"] or 0)

    def proxima_foto_pendente(self, visita_id: int) -> dict | None:
        self.ensure_schema()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM visita_midias
                WHERE visita_id = ?
                  AND tipo = 'foto'
                  AND COALESCE(comentario_status, '') = 'pendente'
                ORDER BY COALESCE(indice, id), id
                LIMIT 1
                """,
                (int(visita_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def existem_fotos_pendentes(self, visita_id: int) -> bool:
        return self.proxima_foto_pendente(visita_id) is not None

    def salvar_comentario_foto(self, midia_id: int, comentario: str) -> dict:
        return self.salvar_comentario_midia(midia_id, comentario)

    def salvar_comentario_midia(self, midia_id: int, comentario: str) -> dict:
        now = _now()
        safe_comment = _clean(comentario) or "Sem comentario informado."
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE visita_midias
                SET comentario = ?, comentario_status = 'resolvido'
                WHERE id = ?
                """,
                (safe_comment, int(midia_id)),
            )
            row = connection.execute(
                "SELECT visita_id FROM visita_midias WHERE id = ?",
                (int(midia_id),),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "UPDATE visitas_tecnicas SET atualizado_em = ? WHERE id = ?",
                    (now, int(row["visita_id"])),
                )
            connection.commit()
        return self.obter_midia(midia_id) or {}

    def fechar_visita(self, visita_id: int) -> dict:
        now = _now()
        return self._update_visita(
            visita_id,
            {"status": "fechada", "estado_fluxo": "fechada", "fechado_em": now},
        )

    def cancelar_visita(self, visita_id: int) -> dict:
        now = _now()
        return self._update_visita(
            visita_id,
            {"status": "cancelada", "estado_fluxo": "cancelada", "fechado_em": now},
        )

    def listar_visitas(
        self,
        periodo: str | None = None,
        data: str | None = None,
        mes: str | None = None,
        fazenda: str | None = None,
        status: str | None = None,
        limite: int | None = None,
    ) -> dict:
        return self.listar_visitas_validas(
            periodo=periodo,
            data=data,
            mes=mes,
            fazenda=fazenda,
            status=status,
            limite=limite,
        )

    def listar_visitas_validas(
        self,
        periodo: str | None = None,
        data: str | None = None,
        mes: str | None = None,
        fazenda: str | None = None,
        status: str | None = None,
        limite: int | None = None,
    ) -> dict:
        self.ensure_schema()
        clauses = ["status IN (?, ?)"]
        values = list(VALID_REPORT_STATUSES)
        normalized_status = _clean(status).lower()
        if normalized_status:
            if normalized_status not in VALID_REPORT_STATUSES:
                return {
                    "visitas": [],
                    "midias": [],
                    "localizacoes": [],
                    "dados_coletados": [],
                }
            clauses = ["status = ?"]
            values = [normalized_status]
        if data:
            clauses.append("data_visita = ?")
            values.append(str(data).strip())
        elif mes:
            clauses.append("substr(data_visita, 1, 7) = ?")
            values.append(str(mes).strip())
        elif periodo == "hoje":
            clauses.append("data_visita = ?")
            values.append(date.today().isoformat())
        if _clean(fazenda):
            clauses.append("LOWER(fazenda) LIKE LOWER(?)")
            values.append(f"%{_clean(fazenda)}%")
        limit_sql = ""
        if limite is not None:
            parsed_limit = max(0, int(limite))
            limit_sql = "LIMIT ?"
            values.append(parsed_limit)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as connection:
            visitas = [
                dict(row)
                for row in connection.execute(
                    f"""
                    SELECT {", ".join(VISITA_COLUMNS)}
                    FROM visitas_tecnicas
                    {where}
                    ORDER BY data_visita DESC, criado_em DESC, id DESC
                    {limit_sql}
                    """,
                    values,
                ).fetchall()
            ]
            ids = [int(item["id"]) for item in visitas]
            midias = self._select_related(connection, "visita_midias", ids)
            localizacoes = self._select_related(connection, "visita_localizacoes", ids)
            dados = self._select_related(connection, "visita_dados_coletados", ids)
        by_visit = {int(item["id"]): item for item in visitas}
        for item in visitas:
            item["midias"] = []
            item["localizacoes"] = []
            item["dados_coletados"] = []
        for item in midias:
            by_visit[int(item["visita_id"])]["midias"].append(item)
        for item in localizacoes:
            by_visit[int(item["visita_id"])]["localizacoes"].append(item)
        for item in dados:
            by_visit[int(item["visita_id"])]["dados_coletados"].append(item)
        return {
            "visitas": visitas,
            "midias": midias,
            "localizacoes": localizacoes,
            "dados_coletados": dados,
        }

    def buscar_visitas_por_fazenda(self, nome_fazenda: str, limite: int | None = None) -> dict:
        return self.listar_visitas_validas(fazenda=nome_fazenda, limite=limite)

    def obter_visita_por_id(self, visita_id: int) -> dict | None:
        return self.obter_visita(visita_id)

    def visita_resumo(self, visita_id: int) -> dict:
        data = self.listar_visitas()
        for visita in data["visitas"]:
            if int(visita["id"]) == int(visita_id):
                return visita
        return {}

    def obter_visita_completa(self, visita_id: int) -> dict | None:
        visita = self.obter_visita(visita_id)
        if visita is None:
            return None

        with closing(self._connect()) as connection:
            midias = self._select_related(connection, "visita_midias", [int(visita_id)])
            localizacoes = self._select_related(
                connection,
                "visita_localizacoes",
                [int(visita_id)],
            )
            dados = self._select_related(
                connection,
                "visita_dados_coletados",
                [int(visita_id)],
            )

        visita["midias"] = midias
        visita["localizacoes"] = localizacoes
        visita["dados_coletados"] = dados
        fotos = [media for media in midias if media.get("tipo") == "foto"]
        videos = [media for media in midias if media.get("tipo") == "video"]
        visita["contadores"] = {
            "midias": len(midias),
            "fotos": len(fotos),
            "videos": len(videos),
            "localizacoes": len(localizacoes),
            "dados_coletados": len(dados),
        }
        return visita

    def obter_ultima_visita(self, telefone_origem: str | None = None) -> dict | None:
        self.ensure_schema()
        phone = normalize_phone(telefone_origem)
        clauses = ["status IN (?, ?)"]
        values = list(VALID_REPORT_STATUSES)
        if phone:
            clauses.append("telefone_origem = ?")
            values.append(phone)
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""
                SELECT {", ".join(VISITA_COLUMNS)}
                FROM visitas_tecnicas
                WHERE {" AND ".join(clauses)}
                ORDER BY
                    CASE WHEN status = 'aberta' THEN 0 ELSE 1 END,
                    data_visita DESC,
                    criado_em DESC,
                    id DESC
                LIMIT 1
                """,
                values,
            ).fetchone()
        if row is None:
            return None
        return self.obter_visita_completa(int(row["id"]))

    @staticmethod
    def gerar_maps_url(latitude: float, longitude: float) -> str:
        return f"https://maps.google.com/?q={latitude},{longitude}"

    def _update_visita(self, visita_id: int, updates: dict) -> dict:
        self.ensure_schema()
        safe_updates = dict(updates)
        safe_updates["atualizado_em"] = _now()
        assignments = ", ".join(f"{column} = ?" for column in safe_updates)
        with closing(self._connect()) as connection:
            connection.execute(
                f"UPDATE visitas_tecnicas SET {assignments} WHERE id = ?",
                (*safe_updates.values(), int(visita_id)),
            )
            connection.commit()
        return self.obter_visita(visita_id) or {}

    def _select_related(
        self,
        connection: sqlite3.Connection,
        table: str,
        visita_ids: list[int],
    ) -> list[dict]:
        if not visita_ids:
            return []
        placeholders = ", ".join("?" for _ in visita_ids)
        order_column = {
            "visita_midias": "enviado_em",
            "visita_localizacoes": "enviado_em",
            "visita_dados_coletados": "criado_em",
        }[table]
        rows = connection.execute(
            f"""
            SELECT *
            FROM {table}
            WHERE visita_id IN ({placeholders})
            ORDER BY {order_column}, id
            """,
            visita_ids,
        ).fetchall()
        return [dict(row) for row in rows]

    def _ensure_columns(
        self,
        connection: sqlite3.Connection,
        table: str,
        columns: dict[str, str],
    ) -> None:
        existing = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column, definition in columns.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _next_media_index(self, connection: sqlite3.Connection, visita_id: int) -> int:
        row = connection.execute(
            """
            SELECT MAX(COALESCE(indice, 0)) AS ultimo
            FROM visita_midias
            WHERE visita_id = ? AND tipo = 'foto'
            """,
            (int(visita_id),),
        ).fetchone()
        return int((row or {"ultimo": 0})["ultimo"] or 0) + 1

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def normalize_phone(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _clean(value: object) -> str:
    return str(value or "").strip()


def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    text = re.sub(r"\b(ha|hectares?|alq|alqueires?)\b", "", text).strip()
    text = text.replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    return float(match.group(0))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
