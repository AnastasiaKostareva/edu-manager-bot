from aiogram.fsm.state import State, StatesGroup


class AddLessonSG(StatesGroup):
    link = State()
    title = State()
    repeat_type = State()
    date = State()
    time = State()


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
