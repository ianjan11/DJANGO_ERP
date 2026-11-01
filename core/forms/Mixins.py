class ErrorClassMixin:
    def apply_error_classes(self):
        for field_name, field in self.fields.items():
            if self.errors.get(field_name):
                existing = field.widget.attrs.get('class', '')
                if 'is-invalid' not in existing:
                    field.widget.attrs['class'] = f'{existing} is-invalid'.strip()
