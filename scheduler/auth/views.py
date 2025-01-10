"""Authentication views"""
from flask import Blueprint, request, redirect, url_for, flash, render_template
from flask import current_app as app

from .ldap import LDAPClient
from .session import get_ldap_client, login_user, logout_user
from .forms import LoginForm

# Create blueprint
auth = Blueprint('auth', __name__)

@auth.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login"""
    form = LoginForm()
    
    if form.validate_on_submit():
        ldap = get_ldap_client()
        success, user = ldap.authenticate(form.username.data, form.password.data)
        
        if success and user:
            login_user(user)
            flash('Successfully logged in', 'success')
            return redirect(url_for('home'))
            
        flash('Invalid username or password', 'error')
        
    return render_template('auth/login.html', form=form)


@auth.route('/logout')
def logout():
    """Handle user logout"""
    logout_user()
    flash('Successfully logged out', 'success')
    return redirect(url_for('home'))