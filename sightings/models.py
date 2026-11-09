from django.db import models


class TickSighting(models.Model):
    """
    Model representing a single tick sighting report in the UK.
    Corresponds to the data provided by https://dev-task.elancoapps.com/
    """
    # Unique identifier provided by the external API (e.g. '02WNholuSg6ndCk4c1dA')
    # Setting primary_key=True ensures duplicate IDs are automatically deduplicated.
    id = models.CharField(max_length=64, primary_key=True)

    # Date and time when the sighting occurred
    date = models.DateTimeField(db_index=True)

    # Location where tick was sighted (e.g. Manchester, London, Glasgow)
    location = models.CharField(max_length=100, db_index=True)

    # Common species name (e.g. Marsh tick, Fox/badger tick)
    species = models.CharField(max_length=100, db_index=True)

    # Scientific Latin name (e.g. Ixodes apronophorus)
    latin_name = models.CharField(max_length=150)

    # Internal timestamp recording when the record was saved
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']
        verbose_name = 'Tick Sighting'
        verbose_name_plural = 'Tick Sightings'
        indexes = [
            models.Index(fields=['location', 'date']),
            models.Index(fields=['species', 'date']),
        ]

    def __str__(self):
        return f"{self.species} sighted in {self.location} on {self.date.strftime('%Y-%m-%d')}"

    def to_dict(self):
        """
        Converts the model instance into a Python dictionary
        suitable for JSON API responses.
        """
        data = {
            'id': self.id,
            'date': self.date.isoformat(),
            'location': self.location,
            'species': self.species,
            'latinName': self.latin_name
        }
        return data
