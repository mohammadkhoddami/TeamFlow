"""Custom admin forms.

User management needs a write-only password field: the table only stores a
bcrypt hash, so the raw password stays inside the form and is hashed by
`UserAdmin.on_model_change` before the row is touched.
"""

from wtforms import BooleanField, Form, PasswordField, StringField
from wtforms.validators import DataRequired, Email, Length, Optional


class UserAdminForm(Form):
    email = StringField(
        "Email", validators=[DataRequired(), Email(), Length(max=255)]
    )
    full_name = StringField(
        "Full name", validators=[DataRequired(), Length(max=255)]
    )
    password = PasswordField(
        "Password",
        validators=[Optional(), Length(min=8, max=128)],
        description="Required when creating a user; leave blank to keep unchanged.",
    )
    is_active = BooleanField("Active", default=True)
    is_superuser = BooleanField("Superuser", default=False)
