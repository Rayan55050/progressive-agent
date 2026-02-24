"""
Progressive Agent — Scheduler Module

Обёртка над APScheduler для управления запланированными задачами.
Поддерживает cron, interval и date триггеры.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger


@dataclass
class JobInfo:
    """Информация о запланированной задаче."""

    id: str
    name: str
    next_run_time: datetime | None
    trigger: str


class Scheduler:
    """
    Планировщик задач на базе APScheduler AsyncIOScheduler.

    Использование:
        scheduler = Scheduler(timezone="Europe/Kiev")
        scheduler.start()

        job_id = scheduler.add_job(
            func=my_async_func,
            trigger="interval",
            minutes=30,
            name="Check emails",
        )

        jobs = scheduler.list_jobs()
        scheduler.remove_job(job_id)
        scheduler.stop()
    """

    def __init__(self, timezone: str = "Europe/Kiev") -> None:
        self._scheduler = AsyncIOScheduler(timezone=timezone)
        self._timezone = timezone

    @property
    def running(self) -> bool:
        """Возвращает True если планировщик запущен."""
        return self._scheduler.running

    def start(self) -> None:
        """Запускает планировщик."""
        if not self._scheduler.running:
            self._scheduler.start()

    def stop(self, wait: bool = True) -> None:
        """
        Останавливает планировщик.

        Args:
            wait: Ждать завершения текущих задач перед остановкой.
        """
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)

    def add_job(
        self,
        func: Callable[..., Any],
        trigger: str | BaseTrigger,
        name: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Добавляет задачу в планировщик.

        Args:
            func: Асинхронная или синхронная функция для выполнения.
            trigger: Тип триггера — "cron", "interval", "date" или объект триггера.
            name: Человекочитаемое название задачи.
            **kwargs: Дополнительные параметры для триггера
                      (minutes, hours, day_of_week, run_date и т.д.).

        Returns:
            job_id: Уникальный идентификатор задачи.
        """
        job_id = str(uuid.uuid4())

        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name or func.__name__,
            **kwargs,
        )

        return job_id

    def remove_job(self, job_id: str) -> None:
        """
        Удаляет задачу из планировщика.

        Args:
            job_id: Идентификатор задачи для удаления.

        Raises:
            JobLookupError: Если задача с таким ID не найдена.
        """
        self._scheduler.remove_job(job_id)

    def list_jobs(self) -> list[JobInfo]:
        """
        Возвращает список всех запланированных задач.

        Returns:
            Список объектов JobInfo с информацией о каждой задаче.
        """
        jobs: list[JobInfo] = []

        for job in self._scheduler.get_jobs():
            jobs.append(
                JobInfo(
                    id=job.id,
                    name=job.name,
                    next_run_time=job.next_run_time,
                    trigger=str(job.trigger),
                )
            )

        return jobs

    def get_job(self, job_id: str) -> JobInfo | None:
        """
        Возвращает информацию о конкретной задаче.

        Args:
            job_id: Идентификатор задачи.

        Returns:
            JobInfo или None если задача не найдена.
        """
        job = self._scheduler.get_job(job_id)

        if job is None:
            return None

        return JobInfo(
            id=job.id,
            name=job.name,
            next_run_time=job.next_run_time,
            trigger=str(job.trigger),
        )

    def pause_job(self, job_id: str) -> None:
        """Ставит задачу на паузу."""
        self._scheduler.pause_job(job_id)

    def resume_job(self, job_id: str) -> None:
        """Снимает задачу с паузы."""
        self._scheduler.resume_job(job_id)

    def __repr__(self) -> str:
        status = "running" if self.running else "stopped"
        job_count = len(self._scheduler.get_jobs()) if self.running else 0
        return f"<Scheduler status={status} jobs={job_count} tz={self._timezone}>"
