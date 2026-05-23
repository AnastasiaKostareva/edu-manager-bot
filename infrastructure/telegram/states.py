from aiogram.fsm.state import State, StatesGroup


class GroupRegSG(StatesGroup):
    waiting_for_username = State()
    role_selection = State()
    name_input = State()
    confirmation = State()


class AddLessonSG(StatesGroup):
    topic = State()
    day_selection = State()
    time = State()
    confirmation = State()
    link = State()
    repeat_type = State()
    chat_reminder = State()


class RemoveLessonSG(StatesGroup):
    select_lesson = State()


class AddReminderSG(StatesGroup):
    target = State()
    student = State()
    teacher = State()
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
