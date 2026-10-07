from __future__ import annotations

import os
from functools import reduce
from typing import Dict, List, Optional, Type, TypeVar

import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class IdentificationRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    title: Optional[str] = Field(default=None, alias="Title")
    category: Optional[str] = Field(default=None, alias="Category")
    attack_type: Optional[str] = Field(default=None, alias="Attack Type")


class AttackDescriptionRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    scenario_description: Optional[str] = Field(default=None, alias="Scenario Description")
    attack_steps: Optional[str] = Field(default=None, alias="Attack Steps")
    tools_used: Optional[str] = Field(default=None, alias="Tools Used")


class TargetVulnerabilityRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    target_type: Optional[str] = Field(default=None, alias="Target Type")
    vulnerability: Optional[str] = Field(default=None, alias="Vulnerability")
    mitre_technique: Optional[str] = Field(default=None, alias="MITRE Technique")


class ImpactProtectionRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    impact: Optional[str] = Field(default=None, alias="Impact")
    detection_method: Optional[str] = Field(default=None, alias="Detection Method")
    solution: Optional[str] = Field(default=None, alias="Solution")


class MetadataRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    tags: Optional[str] = Field(default=None, alias="Tags")
    source: Optional[str] = Field(default=None, alias="Source")


ModelT = TypeVar("ModelT", bound=BaseModel)


class APIClient:
    def __init__(
        self,
        base_url: str,
        login: str,
        password: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.login = login
        self.password = password
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    def __enter__(self) -> "APIClient":
        self._client = httpx.Client(
            base_url=self.base_url,
            auth=httpx.BasicAuth(self.login, self.password),
            timeout=self.timeout,
            headers={"Accept": "application/json"},
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            raise RuntimeError("APIClient должен использоваться через контекстный менеджер 'with'.")
        return self._client

    def _get_json(self, path: str) -> List[Dict]:
        try:
            response = self.client.get(path)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Таймаут при запросе {path}: {exc}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Ошибка HTTP-запроса {path}: {exc}") from exc

        if response.status_code == 401:
            raise RuntimeError("401 Unauthorized: неверный логин или пароль.")
        if response.status_code == 403:
            raise RuntimeError("403 Forbidden: доступ к ресурсу запрещён.")
        if response.status_code == 404:
            raise RuntimeError(f"404 Not Found: эндпоинт {path} не найден.")
        if 500 <= response.status_code < 600:
            raise RuntimeError(f"Ошибка сервера {response.status_code} при запросе {path}.")

        try:
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"HTTP {response.status_code} при запросе {path}: {response.text[:300]}"
            ) from exc
        except ValueError as exc:
            raise RuntimeError(f"Сервер вернул невалидный JSON для {path}.") from exc

        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            payload = payload["data"]

        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise RuntimeError(
                f"Неожиданный формат ответа {path}: ожидался список JSON-объектов."
            )

        return payload

    def _fetch(self, path: str, model: Type[ModelT]) -> List[ModelT]:
        raw_rows = self._get_json(path)
        result: List[ModelT] = []

        for index, row in enumerate(raw_rows):
            try:
                result.append(model.model_validate(row))
            except ValidationError as exc:
                raise RuntimeError(
                    f"Ошибка валидации Pydantic в {path}, строка {index}: {exc}"
                ) from exc

        return result

    def fetch_identification(self) -> List[IdentificationRow]:
        return self._fetch("/api/identification", IdentificationRow)

    def fetch_attack_description(self) -> List[AttackDescriptionRow]:
        return self._fetch("/api/attack_description", AttackDescriptionRow)

    def fetch_target_vulnerability(self) -> List[TargetVulnerabilityRow]:
        return self._fetch("/api/target_vulnerability", TargetVulnerabilityRow)

    def fetch_impact_protection(self) -> List[ImpactProtectionRow]:
        return self._fetch("/api/impact_protection", ImpactProtectionRow)

    def fetch_metadata(self) -> List[MetadataRow]:
        return self._fetch("/api/metadata", MetadataRow)

    @staticmethod
    def _models_to_dataframe(rows: List[BaseModel]) -> pd.DataFrame:
        return pd.DataFrame([row.model_dump(by_alias=True) for row in rows])

    def fetch_all(self) -> pd.DataFrame:
        groups = [
            ("identification", self.fetch_identification()),
            ("attack_description", self.fetch_attack_description()),
            ("target_vulnerability", self.fetch_target_vulnerability()),
            ("impact_protection", self.fetch_impact_protection()),
            ("metadata", self.fetch_metadata()),
        ]

        frames: List[pd.DataFrame] = []
        for name, rows in groups:
            frame = self._models_to_dataframe(rows)
            if "id" not in frame.columns:
                raise RuntimeError(f"В группе {name} отсутствует поле id.")
            if frame["id"].duplicated().any():
                duplicates = frame.loc[frame["id"].duplicated(), "id"].tolist()[:10]
                raise RuntimeError(
                    f"В группе {name} обнаружены повторяющиеся id: {duplicates}"
                )
            print(f"{name}: получено {len(frame)} строк")
            frames.append(frame)

        merged = reduce(
            lambda left, right: pd.merge(left, right, on="id", how="inner"),
            frames,
        )
        return merged.sort_values("id").reset_index(drop=True)


def main() -> None:
    base_url = os.getenv("SQLI_API_URL", "http://193.233.171.205:8000")
    login = os.getenv("SQLI_API_LOGIN", "student")
    password = os.getenv("SQLI_API_PASSWORD", "student_pass")
    output_file = os.getenv("SQLI_OUTPUT", "sql_injections_merged.csv")

    print(f"Подключение к {base_url}")
    with APIClient(base_url, login, password, timeout=60.0) as api:
        dataframe = api.fetch_all()

    dataframe.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\nОбъединено строк: {len(dataframe)}")
    print(f"Столбцов: {len(dataframe.columns)}")
    print(f"CSV сохранён: {output_file}")


if __name__ == "__main__":
    main()
