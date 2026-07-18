import pytest
from unittest.mock import patch, MagicMock
import anchor_doctor_agent

def test_generate_response_calls_gemini():
    with patch('anchor_doctor_agent.genai.GenerativeModel') as mock_model_class:
        mock_instance = mock_model_class.return_value
        mock_response = MagicMock()
        mock_response.text = "Diagnostic check passed."
        mock_instance.generate_content.return_value = mock_response

        response = anchor_doctor_agent.generate_response("Test prompt")
        
        assert response == "Diagnostic check passed."
        # Verify the model was instantiated with the correct system prompt
        mock_model_class.assert_called_with(
            'gemini-1.5-flash', 
            system_instruction=anchor_doctor_agent.SYSTEM_PROMPT
        )
        # Verify generate_content was called with the right prompt
        mock_instance.generate_content.assert_called_once()
        args, kwargs = mock_instance.generate_content.call_args
        assert args[0] == "Test prompt"

def test_generate_response_handles_error():
    with patch('anchor_doctor_agent.genai.GenerativeModel') as mock_model_class:
        mock_model_class.side_effect = Exception("API unreachable")
        
        response = anchor_doctor_agent.generate_response("Test prompt")
        
        assert "Error connecting to AI diagnostic service: API unreachable" in response

def test_generate_response_init_behavior():
    with patch('anchor_doctor_agent.genai.GenerativeModel') as mock_model_class, \
         patch('sys.argv', ['anchor_doctor_agent.py', '--init']):
        mock_instance = mock_model_class.return_value
        mock_response = MagicMock()
        mock_response.text = "- System healthy\\n- Run full system diagnostic"
        mock_instance.generate_content.return_value = mock_response

        # We must import again or just call main, but main calls sys.exit.
        # Just verifying the args logic by mocking main's dependencies,
        # but the simplest way to hit the coverage is simply calling main() and catching SystemExit.
        import sys
        with patch('anchor_doctor_agent.generate_response', return_value="success") as mock_gen:
            with patch('builtins.print'):
                try:
                    anchor_doctor_agent.main()
                except SystemExit:
                    pass
            mock_gen.assert_called_once()
            assert "health report" in mock_gen.call_args[0][0]
