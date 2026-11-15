"""Non-streaming OpenAI Responses HTTP adapter, with injectable transport."""
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from .provider import ProviderError

def http_transport(url, headers, payload, timeout):
    request=Request(url,data=json.dumps(payload).encode(),headers=headers,method='POST')
    with urlopen(request,timeout=timeout) as response:
        return json.load(response)

class ResponsesProvider:
    def __init__(self, settings, *, transport=None, environment=None):
        # Only explicitly constructing a real adapter consults this environment.
        environment=os.environ if environment is None else environment
        self._key=environment.get('API_KEY')
        if not self._key:
            raise ProviderError('API_KEY is required for an explicitly selected real-provider run')
        endpoint=urlsplit(settings.endpoint)
        if endpoint.scheme!='https' or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ProviderError('endpoint must be an HTTPS URL without credentials or query')
        self.settings=settings
        self.transport=transport or http_transport
        self.response_source='openai/'+settings.model

    def request(self, message):
        return dict(model=self.settings.model,instructions=self.settings.prompt,
                    input=[dict(role='user',content=message)],max_output_tokens=self.settings.max_output_tokens,
                    store=False,text=dict(format=dict(type='json_schema',name='access_request',
                                                      strict=True,schema=self.settings.schema)))

    def extract_source(self, message):
        return self.extract(message)

    def extract(self, message):
        try:
            reply=self.transport(self.settings.endpoint,
                {'Authorization':'Bearer '+self._key,'Content-Type':'application/json'},
                self.request(message),self.settings.timeout)
            if not isinstance(reply,dict) or reply.get('error'):
                raise ValueError('provider error')
            status=reply.get('status')
            texts=[]
            for item in reply.get('output',[]):
                if item.get('type')!='message': continue
                for content in item.get('content',[]):
                    if content.get('type')=='refusal':
                        return dict(status='refused',refusal='provider refusal',response_source=self.response_source)
                    if content.get('type')=='output_text': texts.append(content['text'])
                if item.get('status')!='completed': status='incomplete'
            return dict(status=status,output_text=''.join(texts),response_source=self.response_source)
        except Exception:
            # Neither credentials nor untrusted response/error payloads enter logs/history.
            raise ProviderError('HTTP request or response failed; retry extraction') from None

    def evidence(self, message):
        return dict(origin='fake-transport example; no live observation',endpoint=self.settings.endpoint,
                    timeout=self.settings.timeout,headers={'Authorization':'Bearer [REDACTED]'},
                    request=self.request(message),handlers=['completed','refusal','incomplete','HTTP error',
                        'timeout','malformed JSON','schema validation'],
                    transport_failure_provenance='Q-49 pending: configured provider/model identifies attempted origin')
