import chainlit as cl
from agents import function_tool
from chainlit.logger import logger


@function_tool
async def plan_tasks(planned_tasks: list[str]):
    """
    Completely rewrites the list of planned tasks, preserving done tasks.
    Done tasks remain unchanged and are not altered.
    The TaskList will show both DONE and planned tasks.
    """
    logger.warning(f"Planning tasks: {planned_tasks}")
    task_list = cl.user_session.get('task_list')
    if task_list is None:
        task_list = cl.TaskList()
        task_list.status = "Planned"
        cl.user_session.set('task_list', task_list)

    tasks_dict = cl.user_session.get('tasks', {})

    # Preserve done tasks
    done_tasks = {title: task for title, task in tasks_dict.items() if task.status == cl.TaskStatus.DONE}

    # Clear planned tasks by recreating the task list with only done tasks initially
    task_list.tasks = [task for task in task_list.tasks if task.status == cl.TaskStatus.DONE]

    # Add new planned tasks
    new_tasks_dict = done_tasks.copy()
    for task_title in planned_tasks:
        if task_title not in new_tasks_dict:
            task = cl.Task(title=task_title, status=cl.TaskStatus.READY)
            await task_list.add_task(task)
            new_tasks_dict[task_title] = task
        elif new_tasks_dict[task_title].status != cl.TaskStatus.DONE:
            # If it exists but not done, reset to READY (but shouldn't happen since we cleared planned)
            new_tasks_dict[task_title].status = cl.TaskStatus.READY

    cl.user_session.set('tasks', new_tasks_dict)

    # Update overall status if needed
    if all(task.status == cl.TaskStatus.DONE for task in task_list.tasks):
        task_list.status = "Completed"
    else:
        task_list.status = "Planned"

    await task_list.send()

@function_tool
def get_tasks() -> tuple[list[str], list[str]]:
    """
    Returns two lists: tasks that are done and planned tasks.
    Planned tasks include those in READY, RUNNING, FAILED, etc., but not DONE.
    """
    logger.warning("Getting tasks")
    tasks_dict = cl.user_session.get('tasks', {})
    done_tasks = [title for title, task in tasks_dict.items() if task.status == cl.TaskStatus.DONE]
    planned_tasks = [title for title, task in tasks_dict.items() if task.status != cl.TaskStatus.DONE]
    return done_tasks, planned_tasks

@function_tool
async def mark_task_as_done(task_title: str):
    """
    Marks a task as done by updating its status to DONE, only if it's not already done.
    Does not affect done tasks. Refreshes the TaskList, which shows both DONE and planned tasks.
    """
    logger.warning(f"Marking task as done: {task_title}")
    tasks_dict = cl.user_session.get('tasks', {})
    if task_title in tasks_dict and tasks_dict[task_title].status != cl.TaskStatus.DONE:
        tasks_dict[task_title].status = cl.TaskStatus.DONE
        task_list = cl.user_session.get('task_list')
        if task_list:
            # Check if all tasks are done and update overall status
            all_done = all(task.status == cl.TaskStatus.DONE for task in tasks_dict.values())
            if all_done:
                task_list.status = "Completed"
            else:
                task_list.status = "Running..."  # Or keep as is, but assume running when marking
            await task_list.send()

@function_tool
async def mark_task_as_running(task_title: str):
    """
    Marks a task as running by updating its status to RUNNING, only if it's not done.
    Does not affect done tasks. Refreshes the TaskList, which shows both DONE and planned tasks.
    """
    logger.warning(f"Marking task as running: {task_title}")
    tasks_dict = cl.user_session.get('tasks', {})
    if task_title in tasks_dict and tasks_dict[task_title].status != cl.TaskStatus.DONE:
        tasks_dict[task_title].status = cl.TaskStatus.RUNNING
        task_list = cl.user_session.get('task_list')
        if task_list:
            # Update overall status to Running... since a task is now running
            task_list.status = "Running..."
            await task_list.send()