from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from tortoise import connections

from domain.entities import User, UserRole, LessonStatus
from domain.exceptions import PermissionDeniedException


@dataclass
class LessonStatistics:
    """Статистика по занятиям."""
    total_lessons: int
    completed_lessons: int
    cancelled_lessons: int
    overdue_lessons: int
    total_minutes: int
    avg_duration_minutes: float
    completion_rate: float  # процент завершенных от запланированных


@dataclass
class TeacherStatistics:
    """Статистика по преподавателю."""
    teacher_id: int
    teacher_name: str
    lessons_count: int
    total_minutes: int
    avg_duration: float


@dataclass
class PeriodStatistics:
    """Общая статистика за период."""
    period_start: datetime
    period_end: datetime
    lessons: LessonStatistics
    top_teachers: list[TeacherStatistics]
    active_students_count: int
    no_show_rate: float  # процент пропущенных занятий


class StatisticsService:
    """
    Сервис для получения аналитики и статистики.
    """

    async def get_period_statistics(
        self,
        actor: User,
        period_days: int = 30,
        end_date: Optional[datetime] = None
    ) -> PeriodStatistics:
        """
        Получает статистику за указанный период.

        Args:
            actor: Пользователь, запрашивающий статистику (OWNER, ADMIN, TEACHER)
            period_days: Количество дней для анализа
            end_date: Дата окончания периода (по умолчанию - сейчас)

        Returns:
            Статистика за период

        Raises:
            PermissionDeniedException: Если недостаточно прав
        """
        # Проверка прав
        if actor.role not in (UserRole.OWNER, UserRole.ADMIN, UserRole.TEACHER):
            raise PermissionDeniedException(
                "Только преподаватели, администраторы и владелец могут просматривать статистику"
            )

        end_date = end_date or datetime.now()
        start_date = end_date - timedelta(days=period_days)

        conn = connections.get("default")

        # 1. Статистика по занятиям
        lessons_query = """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled,
                COUNT(*) FILTER (WHERE status = 'overdue') as overdue,
                COUNT(*) FILTER (WHERE status = 'no_show') as no_show,
                COALESCE(SUM(duration_minutes) FILTER (WHERE status = 'completed'), 0) as total_minutes,
                COALESCE(AVG(duration_minutes) FILTER (WHERE status = 'completed'), 0) as avg_duration
            FROM lessons
            WHERE created_at >= $1 AND created_at <= $2
        """

        lessons_result = await conn.execute_query_dict(
            lessons_query,
            [start_date, end_date]
        )

        lesson_data = lessons_result[0] if lessons_result else {}
        total = lesson_data.get('total', 0)
        completed = lesson_data.get('completed', 0)
        no_show = lesson_data.get('no_show', 0)

        lessons_stats = LessonStatistics(
            total_lessons=total,
            completed_lessons=completed,
            cancelled_lessons=lesson_data.get('cancelled', 0),
            overdue_lessons=lesson_data.get('overdue', 0),
            total_minutes=int(lesson_data.get('total_minutes', 0)),
            avg_duration_minutes=round(float(lesson_data.get('avg_duration', 0)), 1),
            completion_rate=round((completed / total * 100) if total > 0 else 0, 1)
        )

        # 2. Топ преподавателей
        teachers_query = """
            SELECT
                u.telegram_id,
                COALESCE(u.full_name, u.username) as teacher_name,
                COUNT(l.id) as lessons_count,
                COALESCE(SUM(l.duration_minutes), 0) as total_minutes,
                COALESCE(AVG(l.duration_minutes), 0) as avg_duration
            FROM users u
            JOIN lessons l ON u.telegram_id = l.created_by
            WHERE l.created_at >= $1
                AND l.created_at <= $2
                AND l.status = 'completed'
                AND u.role IN ('teacher', 'admin', 'owner')
            GROUP BY u.telegram_id, u.full_name, u.username
            ORDER BY lessons_count DESC
            LIMIT 10
        """

        teachers_result = await conn.execute_query_dict(
            teachers_query,
            [start_date, end_date]
        )

        top_teachers = [
            TeacherStatistics(
                teacher_id=row['telegram_id'],
                teacher_name=row['teacher_name'],
                lessons_count=row['lessons_count'],
                total_minutes=int(row['total_minutes']),
                avg_duration=round(float(row['avg_duration']), 1)
            )
            for row in teachers_result
        ]

        # 3. Количество активных студентов
        students_query = """
            SELECT COUNT(DISTINCT cm.user_id) as active_students
            FROM chat_members cm
            JOIN users u ON cm.user_id = u.telegram_id
            JOIN chats c ON cm.chat_id = c.chat_id
            WHERE u.role = 'student'
                AND cm.is_active = true
                AND c.is_active = true
        """

        students_result = await conn.execute_query_dict(students_query)
        active_students = students_result[0]['active_students'] if students_result else 0

        # 4. No-show rate
        no_show_rate = round((no_show / total * 100) if total > 0 else 0, 1)

        return PeriodStatistics(
            period_start=start_date,
            period_end=end_date,
            lessons=lessons_stats,
            top_teachers=top_teachers,
            active_students_count=active_students,
            no_show_rate=no_show_rate
        )

    async def get_teacher_statistics(
        self,
        actor: User,
        teacher_id: Optional[int] = None,
        period_days: int = 30
    ) -> TeacherStatistics:
        """
        Получает статистику по конкретному преподавателю.

        Args:
            actor: Пользователь, запрашивающий статистику
            teacher_id: ID преподавателя (если None - статистика по actor)
            period_days: Период для анализа

        Returns:
            Статистика преподавателя
        """
        # Если teacher_id не указан, показываем статистику самого пользователя
        target_id = teacher_id or actor.telegram_id

        # Проверка прав: teacher видит только свою статистику
        if actor.role == UserRole.TEACHER and target_id != actor.telegram_id:
            raise PermissionDeniedException(
                "Преподаватели могут просматривать только свою статистику"
            )

        start_date = datetime.now() - timedelta(days=period_days)
        conn = connections.get("default")

        query = """
            SELECT
                u.telegram_id,
                COALESCE(u.full_name, u.username) as teacher_name,
                COUNT(l.id) as lessons_count,
                COALESCE(SUM(l.duration_minutes), 0) as total_minutes,
                COALESCE(AVG(l.duration_minutes), 0) as avg_duration
            FROM users u
            LEFT JOIN lessons l ON u.telegram_id = l.created_by
                AND l.created_at >= $1
                AND l.status = 'completed'
            WHERE u.telegram_id = $2
            GROUP BY u.telegram_id, u.full_name, u.username
        """

        result = await conn.execute_query_dict(query, [start_date, target_id])

        if not result:
            raise PermissionDeniedException("Преподаватель не найден")

        row = result[0]
        return TeacherStatistics(
            teacher_id=row['telegram_id'],
            teacher_name=row['teacher_name'],
            lessons_count=row['lessons_count'],
            total_minutes=int(row['total_minutes']),
            avg_duration=round(float(row['avg_duration']), 1)
        )

    def format_period_statistics(self, stats: PeriodStatistics) -> str:
        """Форматирует статистику за период в текст для Telegram."""
        lines = [
            "📊 СТАТИСТИКА",
            "",
            f"📅 Период: {stats.period_start.strftime('%d.%m.%Y')} - {stats.period_end.strftime('%d.%m.%Y')}",
            "",
            "📚 ЗАНЯТИЯ:",
            f"  • Всего: {stats.lessons.total_lessons}",
            f"  • Завершено: {stats.lessons.completed_lessons} ({stats.lessons.completion_rate}%)",
            f"  • Отменено: {stats.lessons.cancelled_lessons}",
            f"  • Просрочено: {stats.lessons.overdue_lessons}",
            "",
            "⏱ ВРЕМЯ:",
            f"  • Всего минут: {stats.lessons.total_minutes}",
            f"  • Средняя длительность: {stats.lessons.avg_duration_minutes} мин",
            f"  • Всего часов: {round(stats.lessons.total_minutes / 60, 1)} ч",
            "",
            f"👥 Активных студентов: {stats.active_students_count}",
            f"⚠️ No-show rate: {stats.no_show_rate}%",
        ]

        if stats.top_teachers:
            lines.append("")
            lines.append("🏆 ТОП ПРЕПОДАВАТЕЛЕЙ:")
            for i, teacher in enumerate(stats.top_teachers[:5], 1):
                lines.append(
                    f"  {i}. {teacher.teacher_name}: "
                    f"{teacher.lessons_count} занятий, "
                    f"{teacher.total_minutes} мин"
                )

        return "\n".join(lines)

    def format_teacher_statistics(self, stats: TeacherStatistics, period_days: int) -> str:
        """Форматирует статистику преподавателя в текст."""
        hours = round(stats.total_minutes / 60, 1)

        return (
            f"📊 Статистика: {stats.teacher_name}\n"
            f"📅 За последние {period_days} дней\n\n"
            f"📚 Занятий проведено: {stats.lessons_count}\n"
            f"⏱ Всего времени: {stats.total_minutes} мин ({hours} ч)\n"
            f"📈 Средняя длительность: {stats.avg_duration} мин"
        )
