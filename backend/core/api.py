from typing import cast

from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.http import HttpRequest
from ninja import NinjaAPI
from ninja import Router
from ninja.security import SessionAuth

from core.models import Category
from core.models import Exercise
from core.models import Lift
from core.schema import CategorySchema
from core.schema import ChangePassword
from core.schema import CreateExerciseSchema
from core.schema import CreateLiftSchema
from core.schema import CreateUser
from core.schema import ExerciseSchema
from core.schema import GenericSchema
from core.schema import LiftSchema
from core.schema import Login
from core.schema import UserSchema

categories = Router()
exercises = Router()
lifts = Router()
users = Router()

api = NinjaAPI(docs_url="/docs/")
api.add_router("/categories/", categories, tags=["categories"])
api.add_router("/exercises/", exercises, tags=["exercises"])
api.add_router("/lifts/", lifts, tags=["lifts"])
api.add_router("/users/", users, tags=["users"])


@api.exception_handler(IntegrityError)
def integrity_error_handler(request: HttpRequest, exc: IntegrityError):
    return api.create_response(request, {"detail": str(exc)}, status=400)


@api.exception_handler(ValueError)
def value_error_handler(request: HttpRequest, exc: ValueError):
    return api.create_response(request, {"detail": str(exc)}, status=400)


@api.exception_handler(ValidationError)
def validation_error_handler(request: HttpRequest, exc: ValidationError):
    return api.create_response(
        request,
        {"detail": " ".join([str(i) for i in exc])},
        status=400,
    )


session_auth = SessionAuth(csrf=False)


@categories.get(
    "/",
    auth=session_auth,
    response={200: list[CategorySchema], 401: GenericSchema},
)
def list_categories(request: HttpRequest):
    return 200, Category.objects.all().order_by("-date_created")


@exercises.get(
    "/",
    auth=session_auth,
    response={200: list[ExerciseSchema], 401: GenericSchema},
)
def list_exercises(request: HttpRequest):
    return 200, Exercise.objects.all().order_by("-date_created")


@exercises.post(
    "/", auth=session_auth, response={201: GenericSchema, 401: GenericSchema}
)
def create_exercise(request: HttpRequest, payload: CreateExerciseSchema):
    Exercise.objects.create(name=payload.name, created_by=request.user)
    return 201, {"detail": "Exercise created successfully."}


@lifts.get(
    "/",
    auth=session_auth,
    response={200: list[LiftSchema], 401: GenericSchema},
)
def list_lifts(request: HttpRequest):
    return 200, Lift.objects.filter(user=request.user).order_by("date")


@lifts.post(
    "/",
    auth=session_auth,
    response={201: GenericSchema, 404: GenericSchema, 401: GenericSchema},
)
def create_lift(request: HttpRequest, payload: CreateLiftSchema):
    try:
        exercise = Exercise.objects.get(id=payload.exercise_id)
        Lift.objects.create(
            user=request.user,
            date=payload.date,
            exercise=exercise,
            repetitions=payload.repetitions,
            weight=payload.weight,
        )

        return 201, {"detail": "Lift created successfully."}
    except Exercise.DoesNotExist:
        return 404, {"detail": "Exercise not found."}


@users.post("/", response={201: GenericSchema, 400: GenericSchema})
def create_user(request: HttpRequest, payload: CreateUser):
    # TODO: remove staff user access after editing from frontend is
    # possible
    if get_user_model().objects.filter(username=payload.username).exists():
        return 400, GenericSchema(detail="Username is already used.")
    with transaction.atomic():
        u = get_user_model().objects.create_user(
            is_staff=True,
            first_name=payload.first_name,
            last_name=payload.last_name,
            username=payload.username,
            password=payload.password,
        )
        u.user_permissions.add(Permission.objects.get(codename="add_category"))
        u.user_permissions.add(
            Permission.objects.get(codename="view_category")
        )
        u.user_permissions.add(Permission.objects.get(codename="add_exercise"))
        u.user_permissions.add(
            Permission.objects.get(codename="view_exercise")
        )
        u.user_permissions.add(Permission.objects.get(codename="add_lift"))
        u.user_permissions.add(Permission.objects.get(codename="view_lift"))
        u.save()
    return 201, GenericSchema(detail="Success.")


@users.get(
    "/current/",
    auth=session_auth,
    response={200: UserSchema, 401: GenericSchema},
)
def retrieve_current_user(request: HttpRequest):
    return 200, request.user


@users.post("/login/", response={200: GenericSchema, 400: GenericSchema})
def login(request: HttpRequest, payload: Login):
    user = authenticate(
        request,
        username=payload.username,
        password=payload.password,
    )
    if user is not None:
        django_login(request, user)
        return 200, GenericSchema(detail="Success.")
    else:
        return 400, GenericSchema(detail="Invalid credentials.")


@users.post("/logout/", response=GenericSchema)
def logout(request: HttpRequest):
    django_logout(request)
    return GenericSchema(detail="Success.")


@users.post(
    "/change-password/",
    auth=session_auth,
    response={200: GenericSchema, 400: GenericSchema, 401: GenericSchema},
)
def change_password(request: HttpRequest, payload: ChangePassword):
    user = cast(AbstractBaseUser, request.user)
    if not user.check_password(payload.current_password):
        return 400, {"detail": "Current password is incorrect."}
    validate_password(payload.new_password)
    user.set_password(payload.new_password)
    user.save()
    update_session_auth_hash(request, user)
    return GenericSchema(detail="Password changed successfully.")
