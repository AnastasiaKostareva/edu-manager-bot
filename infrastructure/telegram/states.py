from aiogram.fsm.state import State, StatesGroup


class GroupRegSG(StatesGroup):
    waiting_for_username = State()   # Ожидание ввода @username или /done
    role_selection = State()         # Выбор роли для текущего пользователя
    name_input = State()             # Ввод имени
    confirmation = State()

class AddLessonSG(StatesGroup):
    topic = State()           # Тема занятия
    day_selection = State()   # Выбор дня (кнопки) или ввод даты вручную
    time = State()            # Время занятия
    confirmation = State()    # Подтверждение данных
    link = State()
    duration = State()        # Длительность занятия


class RemoveLessonSG(StatesGroup):
    select_lesson = State()


class AddReminderSG(StatesGroup):
    target = State()
    student = State()
    lesson = State()
    topic = State()
    custom_text = State()
    time = State()
    custom_time = State()


class RemoveReminderSG(StatesGroup):
    target = State()
    student = State()
    select_reminder = State()


class LessonManagementSG(StatesGroup):
    select_lesson = State()


class SqlConsoleSG(StatesGroup):
    query = State()


class StartLessonSG(StatesGroup):
    confirm = State()


class CompleteLessonSG(StatesGroup):
    custom_duration = State()


class EditLessonSG(StatesGroup):
    field = State()
    new_duration = State()
